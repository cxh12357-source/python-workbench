import ctypes
import os
import subprocess
import time
from ctypes import wintypes

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.runner import ROOT, TERMINAL, Runner

ORIGIN = "http://127.0.0.1:8765"
BOOTSTRAP = {"Sec-Fetch-Site": "same-origin", "X-Runner-Bootstrap": "1"}


@pytest.fixture
def client():
    with TestClient(create_app(), base_url=ORIGIN) as browser:
        session = browser.get("/api/session", headers=BOOTSTRAP)
        assert session.status_code == 200
        browser.headers.update({"X-Runner-Token": session.json()["token"]})
        yield browser


def launch(client, code, stdin="", argv=None):
    response = client.post("/api/runs", json={"code": code, "stdin": stdin, "argv": argv or []})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def wait(client, run_id, deadline=8):
    until = time.monotonic() + deadline
    while time.monotonic() < until:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        result = response.json()
        if result["status"] in TERMINAL:
            return result
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not finish")


def await_output(client, run_id, fragment, deadline=3):
    until = time.monotonic() + deadline
    while time.monotonic() < until:
        result = client.get(f"/api/runs/{run_id}").json()
        if fragment in result["stdout"]:
            return result
        time.sleep(0.02)
    raise AssertionError(f"Missing output {fragment!r}: {result}")


def is_alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def await_dead(*pids):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        if all(not is_alive(pid) for pid in pids):
            return
        time.sleep(0.03)
    assert all(not is_alive(pid) for pid in pids), f"Process tree survived: {pids}"


def test_chinese_print_end_and_stderr_without_newline(client):
    result = wait(client, launch(client,
        "import sys\nprint('中文输出', end='')\nsys.stderr.write('中文错误')"))
    assert result["status"] == "completed"
    assert result["stdout"] == "中文输出"
    assert result["stderr"] == "中文错误"
    assert result["exit_code"] == 0
    assert result["duration_ms"] > 0


def test_multiline_stdin_blank_line_and_argv(client):
    result = wait(client, launch(client,
        "import sys\nprint(repr(input()))\nprint(repr(input()))\nprint(repr(input()))\nprint(sys.argv[1:])",
        "第一行\n\n最后一行", ["中文 参数", "--count=2"]))
    assert result["status"] == "completed"
    assert result["stdout"] == "'第一行'\r\n''\r\n'最后一行'\r\n['中文 参数', '--count=2']\r\n"


def test_exception_and_eof(client):
    result = wait(client, launch(client, "input('输入: ')", ""))
    assert result["status"] == "error"
    assert result["stdout"] == "输入: "
    assert "EOFError" in result["stderr"]
    assert result["exit_code"] == 1
    result = wait(client, launch(client, "raise ValueError('中文错误')"))
    assert result["status"] == "error"
    assert "ValueError: 中文错误" in result["stderr"]


def test_default_timeout_does_not_block_health(client):
    run_id = launch(client, "while True:\n    pass")
    started = time.monotonic()
    assert client.get("/health").json() == {"status": "ok"}
    assert time.monotonic() - started < 0.5
    busy = client.post("/api/runs", json={"code": "print('busy')"})
    assert busy.status_code == 409
    result = wait(client, run_id)
    assert result["status"] == "timeout"
    assert 4800 <= result["duration_ms"] < 7000
    # Windows Job-on-close may terminate with exit code 0. Status carries reason.
    assert isinstance(result["exit_code"], int)
    assert wait(client, launch(client, "print('再次运行')"))["status"] == "completed"


def test_cumulative_output_limit_and_two_pipes(client):
    result = wait(client, launch(client,
        "import sys\nwhile True:\n    sys.stdout.write('o' * 4096)\n    sys.stderr.write('e' * 4096)"))
    assert result["status"] == "output_limit"
    assert result["output_bytes"] == 102400
    assert len(result["stdout"].encode()) + len(result["stderr"].encode()) == 102400
    assert len(result["stdout"]) > 0 and len(result["stderr"]) > 0


def test_stop_reclaims_child_and_grandchild_and_preserves_unrelated_process(client):
    unrelated = subprocess.Popen([str(ROOT / ".venv-learning/Scripts/python.exe"),
                                  "-c", "import time; time.sleep(30)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    grandchild = "import time; time.sleep(60)"
    child = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
        "print('grandchild',p.pid,flush=True); time.sleep(60)"
    )
    code = (
        "import subprocess,sys,time\n"
        f"p=subprocess.Popen([sys.executable,'-u','-c',{child!r}])\n"
        "print('child',p.pid,flush=True)\n"
        "time.sleep(60)"
    )
    try:
        run_id = launch(client, code)
        result = await_output(client, run_id, "grandchild")
        pids = [int(line.split()[1]) for line in result["stdout"].splitlines()]
        assert len(pids) == 2 and all(is_alive(pid) for pid in pids)
        assert client.delete(f"/api/runs/{run_id}").status_code == 200
        assert wait(client, run_id)["status"] == "stopped"
        await_dead(*pids)
        assert unrelated.poll() is None
        assert client.get("/health").status_code == 200
        assert wait(client, launch(client, "print('ok')"))["status"] == "completed"
    finally:
        unrelated.kill()
        unrelated.wait(timeout=3)


@pytest.mark.parametrize("mode", ["normal", "timeout"])
def test_parent_exit_or_timeout_reclaims_child(client, mode):
    code = (
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "print(p.pid,flush=True)\n"
        + ("time.sleep(60)" if mode == "timeout" else "time.sleep(0.1)")
    )
    run_id = launch(client, code)
    result = wait(client, run_id)
    pid = int(result["stdout"].strip())
    assert result["status"] == ("timeout" if mode == "timeout" else "completed")
    await_dead(pid)


def test_shutdown_reclaims_running_process():
    engine = Runner()
    with TestClient(create_app(engine), base_url=ORIGIN) as client:
        token = client.get("/api/session", headers=BOOTSTRAP).json()["token"]
        client.headers["X-Runner-Token"] = token
        run_id = launch(client, "import os,time\nprint(os.getpid(),flush=True)\ntime.sleep(60)")
        result = await_output(client, run_id, "\n")
        pid = int(result["stdout"].strip())
        assert is_alive(pid)
    await_dead(pid)
    assert engine.runs[run_id].status == "stopped"


def test_cross_origin_host_and_session_bootstrap_rejected(client):
    assert client.get("/api/session").status_code == 403
    for headers in (
        {"Origin": "https://attacker.example"},
        {"Origin": "http://localhost:8765"},
        {"Origin": "http://127.0.0.1:9999"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Host": "attacker.example:8765"},
    ):
        assert client.get("/api/session", headers={**BOOTSTRAP, **headers}).status_code == 403
        assert client.post("/api/runs", json={"code": "print('no')"}, headers=headers).status_code == 403
    assert client.post("/api/runs", json={"code": "print('no')"}, headers={"X-Runner-Token": "wrong"}).status_code == 403
    assert client.get("/health", headers={"Origin": ORIGIN}).status_code == 200


def test_session_tokens_change_between_app_instances():
    with TestClient(create_app(), base_url=ORIGIN) as one, TestClient(create_app(), base_url=ORIGIN) as two:
        first = one.get("/api/session", headers=BOOTSTRAP).json()["token"]
        second = two.get("/api/session", headers=BOOTSTRAP).json()["token"]
        assert first != second
        assert two.post("/api/runs", json={"code": "pass"}, headers={"X-Runner-Token": first}).status_code == 403


def test_request_validation_and_unknown_run(client):
    assert client.post("/api/runs", json={"code": "pass", "argv": ["ok", 123]}).status_code == 422
    assert client.get("/api/runs/missing").status_code == 404
    assert client.delete("/api/runs/missing").status_code == 404


def test_interpreter_is_learning_venv_and_temp_cwd_is_cleaned(client):
    result = wait(client, launch(client, "import sys,os\nprint(sys.executable)\nprint(os.getcwd())"))
    executable, cwd = result["stdout"].splitlines()
    assert os.path.normcase(executable) == os.path.normcase(str(ROOT / ".venv-learning/Scripts/python.exe"))
    assert not os.path.exists(cwd)


def test_large_prefilled_stdin_without_reads_does_not_hang(client):
    result = wait(client, launch(client, "print('done')", "x" * 256000))
    assert result["status"] == "completed"
    assert result["stdout"] == "done\r\n"
