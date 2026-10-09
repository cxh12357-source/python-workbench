"""Small transactional store for one learner; execution history is separate from UI state."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .backup_codec import encode_backup

ROOT = Path(__file__).resolve().parents[1]
UNIT_IDS = {f"week-{n}" for n in range(10)} | {"final-project"}
STEPS = {"video", "points", "example", "practice", "review"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def text_value(value, maximum=100_000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"文本必须是字符串，且不超过 {maximum} 个字符。")
    return value


def validate_files(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 50:
        raise ValueError("项目需要 1–50 个文本文件。")
    clean = {}
    names = set()
    for name, content in files.items():
        text_value(name, 180)
        path = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or path.is_absolute()
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or any(part.startswith(".") or part.endswith((".", " ")) for part in path.parts)
                or any(char in name for char in '<>"|?*\x00\r\n')
                or any(part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]} for part in path.parts)
                or name.casefold() in names):
            raise ValueError("文件名必须是项目内的普通相对路径，不能指向外部目录。")
        clean[name] = text_value(content)
        names.add(name.casefold())
    if len(json.dumps(clean, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
        raise ValueError("项目文本总大小不能超过 1 MB。")
    return clean


def validate_project(value):
    if not isinstance(value, dict):
        raise ValueError("项目格式不正确。")
    files = validate_files(value.get("files"))
    entrypoint = text_value(value.get("entrypoint", "project.py"), 180)
    if entrypoint not in files or not entrypoint.endswith(".py"):
        raise ValueError("运行入口必须是项目中已有的 Python 文件。")
    return {"files": files, "entrypoint": entrypoint,
            "notes": text_value(value.get("notes", ""), 20_000)}


def validate_state(value):
    if not isinstance(value, dict) or value.get("current_unit") not in UNIT_IDS:
        raise ValueError("学习记录中的课程单元不正确。")
    units = value.get("units", {})
    if not isinstance(units, dict) or not set(units).issubset(UNIT_IDS):
        raise ValueError("学习记录包含未知课程。")
    clean = {}
    for key, item in units.items():
        if not isinstance(item, dict):
            raise ValueError("单元记录格式不正确。")
        steps = item.get("completed_steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, str) or step not in STEPS for step in steps):
            raise ValueError("学习步骤不正确。")
        drafts = item.get("drafts", {})
        if not isinstance(drafts, dict) or len(drafts) > 20:
            raise ValueError("代码草稿格式不正确。")
        status = item.get("official_status", "not_started")
        if not isinstance(status, str) or status not in {"not_started", "working", "done"}:
            raise ValueError("官方作业状态不正确。")
        clean[key] = {
            "completed_steps": list(dict.fromkeys(steps)),
            "note": text_value(item.get("note", ""), 20_000),
            "code": text_value(item.get("code", "")),
            "drafts": {text_value(k, 100): text_value(v) for k, v in drafts.items()},
            "selected_exercise": text_value(item.get("selected_exercise", ""), 100),
            "selected_example": text_value(item.get("selected_example", ""), 100),
            "video_url": text_value(item.get("video_url", ""), 2000),
            "official_status": status,
            "official_note": text_value(item.get("official_note", ""), 10_000),
        }
    result = {"current_unit": value["current_unit"], "units": clean}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("学习记录总大小不能超过 4 MB。")
    return result


def initial_project():
    return {
        "entrypoint": "project.py", "notes": "",
        "files": {
            "project.py": 'def main():\n    # 从一个你关心的小问题开始，把目标写在 README 中。\n    print("我的 Python 项目")\n\n\nif __name__ == "__main__":\n    main()\n',
            "test_project.py": "# 为你自己编写的函数添加 pytest 测试。\n# 示例命名：def test_your_function():\n# 不要只测试正常输入，也试试边界和错误输入。\n",
            "requirements.txt": "# 在这里逐行记录你的项目所需的第三方依赖。\n",
            "README.md": "# 我的 Python 项目\n\n## 项目解决什么问题\n\n请写下你自己的想法。\n\n## 如何运行\n\n## 函数与测试\n\n## 演示视频\n\n## 设计选择\n",
        },
    }


class LearningStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / "local-data/workbench.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS documents (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO documents VALUES (?, ?)", ("state", json.dumps({"current_unit": "week-0", "units": {}})))
            db.execute("INSERT OR IGNORE INTO documents VALUES (?, ?)", ("project", json.dumps(initial_project(), ensure_ascii=False)))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _read(db, name):
        return json.loads(db.execute("SELECT value FROM documents WHERE name=?", (name,)).fetchone()[0])

    @staticmethod
    def _write(db, name, value):
        db.execute("UPDATE documents SET value=? WHERE name=?", (json.dumps(value, ensure_ascii=False), name))

    def document(self, name):
        with self.lock, self.connect() as db:
            return self._read(db, name)

    def save(self, name, value):
        clean = validate_state(value) if name == "state" else validate_project(value)
        with self.lock, self.connect() as db:
            self._write(db, name, clean)
        return clean

    def attempts(self):
        with self.lock, self.connect() as db:
            return [{**json.loads(value), "id": str(key)} for key, value in db.execute("SELECT id, value FROM attempts ORDER BY id")]

    def record(self, exercise, code, result):
        value = {"exercise_id": exercise["id"], "unit_id": exercise["unit_id"],
                 "title": exercise["title"], "code": code,
                 "created_at": timestamp(), "result": result}
        with self.lock, self.connect() as db:
            cursor = db.execute("INSERT INTO attempts(value) VALUES (?)", (json.dumps(value, ensure_ascii=False),))
            return str(cursor.lastrowid)

    def state(self):
        result = self.document("state")
        groups = {}
        for attempt in self.attempts():
            groups.setdefault(attempt["exercise_id"], []).append(attempt)
        progress, mistakes = {}, []
        for key, attempts in groups.items():
            last = attempts[-1]
            progress[key] = {"passed": last["result"]["passed"], "attempts": len(attempts),
                             "last_attempt_at": last["created_at"]}
            failures = [a for a in attempts if not a["result"]["passed"]]
            if failures:
                failure = failures[-1]
                messages = [c.get("message", c["name"]) for c in failure["result"]["cases"] if not c["passed"]]
                mistakes.append({"id": failure["id"], "unit_id": failure["unit_id"],
                                 "exercise_id": key, "title": failure["title"], "code": failure["code"],
                                 "created_at": failure["created_at"], "message": "；".join(messages)[:2000],
                                 "resolved": bool(last["result"]["passed"])})
        return {**result, "exercise_progress": progress, "mistakes": list(reversed(mistakes))}

    def backup(self):
        with self.lock:
            return {"format": "cs50p-workbench", "schema_version": 1,
                    "created_at": timestamp(), "state": self.document("state"),
                    "project": self.document("project"), "attempts": self.attempts()}

    def restore(self, value, exercises):
        if not isinstance(value, dict) or value.get("format") != "cs50p-workbench" or value.get("schema_version") != 1:
            raise ValueError("这不是支持的工作台备份文件。")
        state = validate_state(value.get("state"))
        project = validate_project(value.get("project"))
        attempts = value.get("attempts", [])
        if not isinstance(attempts, list) or len(attempts) > 100_000:
            raise ValueError("练习历史格式不正确。")
        clean = []
        for attempt in attempts:
            if not isinstance(attempt, dict) or attempt.get("exercise_id") not in exercises:
                raise ValueError("备份练习历史包含未知题目。")
            exercise = exercises[attempt["exercise_id"]]
            result = attempt.get("result", {})
            cases = result.get("cases", []) if isinstance(result, dict) else []
            if (not isinstance(cases, list) or not cases or len(cases) > 100
                    or any(not isinstance(c, dict) or type(c.get("passed")) is not bool or not isinstance(c.get("name"), str) for c in cases)
                    or type(result.get("passed")) is not bool
                    or result["passed"] != all(c["passed"] for c in cases)):
                raise ValueError("备份中的检查结果不完整。")
            clean_cases = []
            for case in cases:
                clean_case = {"name": text_value(case["name"], 200), "passed": case["passed"]}
                for key in ("message", "expected", "actual"):
                    if key in case:
                        clean_case[key] = text_value(case[key], 100_000)
                clean_cases.append(clean_case)
            created_at = text_value(attempt.get("created_at", ""), 100)
            try:
                datetime.fromisoformat(created_at)
            except ValueError as error:
                raise ValueError("备份中的练习时间不正确。") from error
            clean_result = {"exercise_id": exercise["id"], "passed": result["passed"],
                            "cases": clean_cases, "total": len(clean_cases),
                            "passed_count": sum(case["passed"] for case in clean_cases)}
            clean.append({"exercise_id": exercise["id"], "unit_id": exercise["unit_id"],
                          "title": exercise["title"], "code": text_value(attempt.get("code", "")),
                          "created_at": created_at, "result": clean_result})
        with self.lock:
            directory = self.path.parent / "backups"
            directory.mkdir(exist_ok=True)
            name = datetime.now(timezone.utc).strftime("before-restore-%Y%m%d-%H%M%S-%f.json")
            (directory / name).write_text(encode_backup(self.backup()), encoding="utf-8")
            with self.connect() as db:
                self._write(db, "state", state)
                self._write(db, "project", project)
                db.execute("DELETE FROM attempts")
                db.executemany("INSERT INTO attempts(value) VALUES (?)", [(json.dumps(a, ensure_ascii=False),) for a in clean])
        return self.state()
