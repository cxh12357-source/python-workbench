"""Run trusted learner code out-of-process with bounded lifetime and output."""

import asyncio
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .windows_job import JobPopen, WindowsJob
from .artifacts import Artifact, collect_artifacts

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "error", "timeout", "output_limit", "stopped"}


class RunnerBusy(Exception):
    pass


def validate_files(files, entrypoint):
    if not isinstance(files, dict) or not files or len(files) > 50:
        raise ValueError("项目需包含 1 至 50 个文本文件。")
    result = {}
    seen = set()
    size = 0
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                *[f"LPT{i}" for i in range(1, 10)]}
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise ValueError("项目文件名与内容必须为字符串。")
        normalized = name.replace("\\", "/")
        parts = normalized.split("/")
        if (len(name) > 240 or PurePosixPath(normalized).is_absolute()
                or any(part in {"", ".", ".."} or part.rstrip(" .") != part
                       or any(ch in part for ch in ':*?"<>|')
                       or any(ord(ch) < 32 for ch in part)
                       or part.split(".")[0].upper() in reserved for part in parts)):
            raise ValueError("文件名必须是项目内合法的相对路径。")
        if normalized.casefold() in seen:
            raise ValueError("项目文件名重复。")
        seen.add(normalized.casefold())
        size += len(content.encode("utf-8"))
        if size > 1_048_576:
            raise ValueError("项目文本内容超过 1 MiB。")
        result[normalized] = content
    entrypoint = entrypoint.replace("\\", "/")
    if entrypoint not in result:
        raise ValueError("入口文件不在项目文件中。")
    return result, entrypoint


@dataclass
class Run:
    id: str
    code: str
    stdin: str
    argv: list[str]
    interactive: bool = False
    timeout: float = 5.0
    files: dict[str, str] = field(default_factory=dict)
    entrypoint: str = "main.py"
    pytest_mode: bool = False
    status: str = "queued"
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    exit_code: int | None = None
    duration_ms: int = 0
    stop_reason: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task | None = None
    input_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=20))
    input_open: bool = True
    input_bytes: int = 0
    artifacts: dict[str, Artifact] = field(default_factory=dict)

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id, "status": self.status,
                "stdout": bytes(self.stdout).decode("utf-8", errors="replace"),
                "stderr": bytes(self.stderr).decode("utf-8", errors="replace"),
                "exit_code": self.exit_code, "duration_ms": self.duration_ms,
                "output_bytes": len(self.stdout) + len(self.stderr),
                "interactive": self.interactive, "input_open": self.input_open,
                "timeout_seconds": self.timeout,
                "artifacts": [{"name": name, "size": len(item.data), "mime": item.mime}
                              for name, item in self.artifacts.items()],
            }

    def request_stop(self, reason="stopped"):
        with self.lock:
            if self.status in TERMINAL:
                return
            if self.stop_reason is None:
                self.stop_reason = reason
            self.stop_event.set()


class Runner:
    def __init__(self, interpreter=None, timeout=5.0, output_limit=100 * 1024,
                 max_concurrent=1):
        self.interpreter = Path(interpreter or ROOT / ".venv-learning/Scripts/python.exe")
        self.timeout = timeout
        self.output_limit = output_limit
        self.max_concurrent = max_concurrent
        self.runs: dict[str, Run] = {}
        self.closing = False

    def start(self, code=None, stdin="", argv=None, *, interactive=False, timeout=None,
              files=None, entrypoint="main.py", pytest_mode=False):
        # start() and shutdown() are called only on the application's event loop.
        active = sum(run.status not in TERMINAL for run in self.runs.values())
        if self.closing or active >= self.max_concurrent:
            raise RunnerBusy("已有代码正在运行，请先停止或等待结束。")
        if not self.interpreter.is_file():
            raise RuntimeError("学习环境不存在，请先运行 scripts/setup.ps1。")
        selected_timeout = timeout if timeout is not None else (120.0 if interactive else self.timeout)
        if not 0 < selected_timeout <= 300:
            raise ValueError("运行时限必须大于 0 且不超过 300 秒。")
        project_files = dict(files or {})
        if code is not None:
            project_files[entrypoint] = code
        elif not project_files:
            project_files[entrypoint] = ""
        project_files, entrypoint = validate_files(project_files, entrypoint)
        # Keep bounded session history; entries own no persistent learner data.
        while len(self.runs) >= 100:
            oldest = next(iter(self.runs))
            if self.runs[oldest].status not in TERMINAL:
                break
            del self.runs[oldest]
        # At most 20 recent runs hold <=1MiB artifacts each, including this run.
        for old_run in list(self.runs.values())[:-19]:
            with old_run.lock:
                old_run.artifacts.clear()
        run = Run(uuid.uuid4().hex, code, stdin, list(argv or []), interactive,
                  selected_timeout, project_files, entrypoint, pytest_mode)
        run.input_bytes = len(stdin.encode("utf-8"))
        self.runs[run.id] = run
        run.task = asyncio.create_task(asyncio.to_thread(self._execute, run))
        return run

    def send_input(self, run_id, text, eof=False):
        run = self.runs[run_id]
        with run.lock:
            if not run.interactive or not run.input_open or run.status in TERMINAL:
                raise RunnerBusy("本次运行的输入已关闭。")
            payload = (text + "\n").encode("utf-8") if text or not eof else b""
            if run.input_bytes + len(payload) > 256_000:
                raise ValueError("累计输入超过 256 KB。")
            try:
                run.input_queue.put_nowait((payload, eof))
            except queue.Full as error:
                raise RunnerBusy("输入队列已满，请等待程序读取。") from error
            run.input_bytes += len(payload)
            if eof:
                run.input_open = False
        return run

    async def shutdown(self):
        self.closing = True
        tasks = []
        for run in self.runs.values():
            run.request_stop()
            if run.task:
                tasks.append(run.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _execute(self, run):
        started = time.monotonic()
        process = None
        job = None
        threads = []
        final_status = "error"
        try:
            if run.stop_event.is_set():
                with run.lock:
                    final_status = "stopped"
                return
            with tempfile.TemporaryDirectory(prefix="python-workbench-") as temp:
                originals = {}
                for name, content in run.files.items():
                    target = Path(temp) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                    originals[name] = target.read_bytes()
                script = Path(temp) / run.entrypoint
                job = WindowsJob()
                env = os.environ.copy()
                # User code never receives the application's session token.
                env.pop("RUNNER_SESSION_TOKEN", None)
                env["PYTHONUTF8"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
                process = JobPopen(
                    [str(self.interpreter), "-u", "-X", "utf8",
                     str(Path(__file__).with_name("bootstrap.py")),
                     "pytest" if run.pytest_mode else "script", str(script), *run.argv],
                    cwd=temp, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, shell=False, bufsize=0, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    job=job,
                )
                # Before this succeeds, bootstrap can only wait on its stdin gate.
                with run.lock:
                    run.status = "running"
                for pipe, target in ((process.stdout, run.stdout), (process.stderr, run.stderr)):
                    thread = threading.Thread(target=self._read, args=(run, pipe, target), daemon=True)
                    threads.append(thread)
                    thread.start()
                writer = threading.Thread(target=self._feed, args=(process, run), daemon=True)
                threads.append(writer)
                writer.start()
                while process.poll() is None:
                    elapsed = time.monotonic() - started
                    with run.lock:
                        run.duration_ms = round(elapsed * 1000)
                    if elapsed >= run.timeout:
                        run.request_stop("timeout")
                    if run.stop_event.wait(0.01):
                        job.close()
                        break
                # Even normal parent exit must reclaim descendants holding pipes.
                job.close()
                process.wait(timeout=3)
                for thread in threads:
                    thread.join(timeout=3)
                if any(thread.is_alive() for thread in threads):
                    raise RuntimeError("运行结束后未能回收输入输出线程。")
                artifacts = collect_artifacts(temp, originals)
                with run.lock:
                    run.artifacts = artifacts
                    run.exit_code = process.returncode
                    final_status = run.stop_reason or (
                        "completed" if process.returncode == 0 else "error"
                    )
        except Exception as error:
            if job:
                job.close()
            if process and process.poll() is None:
                # Startup failure before successful assignment has no user code.
                process.kill()
                process.wait(timeout=3)
            for thread in threads:
                thread.join(timeout=3)
            with run.lock:
                remaining = self.output_limit - len(run.stdout) - len(run.stderr)
                run.stderr.extend(f"运行服务错误：{error}".encode("utf-8")[:remaining])
                final_status = "error"
                run.exit_code = process.returncode if process else None
        finally:
            if process:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    pipe.close()
            with run.lock:
                run.status = final_status
                run.input_open = False
                run.duration_ms = round((time.monotonic() - started) * 1000)

    def _read(self, run, pipe, target):
        while chunk := pipe.read(4096):
            with run.lock:
                remaining = self.output_limit - len(run.stdout) - len(run.stderr)
                target.extend(chunk[:remaining])
                exceeded = len(chunk) > remaining
            if exceeded:
                run.request_stop("output_limit")
                return

    @staticmethod
    def _feed(process, run):
        def write(data):
            while data:
                count = process.stdin.write(data)
                if not count:
                    break
                data = data[count:]
        try:
            write(b"PYTHON_WORKBENCH_START\n")
            write(run.stdin.encode("utf-8"))
            if run.interactive:
                while not run.stop_event.is_set() and process.poll() is None:
                    try:
                        data, eof = run.input_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    write(data)
                    if eof:
                        break
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()
            with run.lock:
                run.input_open = False
