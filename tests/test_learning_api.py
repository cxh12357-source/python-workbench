"""Check genuine grading and data recovery, using temporary learner records."""
import asyncio
import copy
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.backup_codec import encode_backup
from server.learning_api import grade_exercise, load_course
from server.runner import Runner, TERMINAL
from server.storage import LearningStore, validate_project


@pytest.fixture
def learning_client(tmp_path):
    store = LearningStore(tmp_path / "learner.sqlite3")
    with TestClient(create_app(store=store), base_url="http://127.0.0.1:8765") as client:
        session = client.get("/api/session", headers={"Sec-Fetch-Site": "same-origin", "X-Runner-Bootstrap": "1"})
        client.headers["X-Runner-Token"] = session.json()["token"]
        yield client, store


def test_course_has_30_original_exercises_and_hides_teacher_checks(learning_client):
    client, _ = learning_client
    data = client.get("/api/course").json()
    assert len(data["index"]["units"]) == 11
    assert set(data["lessons"]) == {unit["id"] for unit in data["index"]["units"]}
    exercises = [ex for unit in data["lessons"].values() for ex in unit["exercises"]]
    assert len(exercises) == 30
    assert all(ex["source_type"] == "original" and len(ex["hints"]) == 3 for ex in exercises)
    assert all(not {"tests", "variants", "wrong_solution"} & set(ex) for ex in exercises)
    assert data["index"]["units"][9]["resources"]["problemSet"]["url"] is None


def test_all_reference_solutions_pass_and_representative_bugs_fail():
    async def check_all():
        engine = Runner()
        _, _, exercises = load_course()
        try:
            for exercise in exercises.values():
                correct = await grade_exercise(engine, exercise, exercise["solution"])
                assert correct["passed"], (exercise["id"], correct)
                wrong = await grade_exercise(engine, exercise, exercise["wrong_solution"])
                assert not wrong["passed"], (exercise["id"], wrong)
        finally:
            await engine.shutdown()
    asyncio.run(check_all())


def test_real_attempts_generate_mistakes_and_resolve_them(learning_client):
    client, _ = learning_client
    _, _, exercises = load_course()
    exercise = exercises["week-0-ex-1"]
    failed = client.post("/api/checks", json={"exercise_id": exercise["id"], "code": exercise["wrong_solution"]})
    assert failed.status_code == 200, failed.text
    assert not failed.json()["passed"]
    state = client.get("/api/state").json()
    assert len(state["mistakes"]) == 1 and not state["mistakes"][0]["resolved"]
    # UI autosave cannot overwrite real grading history.
    state["mistakes"] = []
    state["exercise_progress"] = {exercise["id"]: {"passed": True}}
    assert client.put("/api/state", json=state).status_code == 200
    assert len(client.get("/api/state").json()["mistakes"]) == 1
    passed = client.post("/api/checks", json={"exercise_id": exercise["id"], "code": exercise["solution"]})
    assert passed.json()["passed"]
    state = client.get("/api/state").json()
    assert state["mistakes"][0]["resolved"]
    assert state["exercise_progress"][exercise["id"]]["attempts"] == 2


def test_backup_roundtrip_and_invalid_restore_preserve_current_data(learning_client):
    client, store = learning_client
    saved = {"current_unit": "week-6", "units": {"week-6": {
        "note": "我的中文笔记", "code": "print('我的代码')", "completed_steps": ["video"],
        "drafts": {"week-6-ex-1": "def read_notes(path):\n    return []"},
        "selected_example": "week-6-example-1", "official_status": "working", "official_note": "读题中",
    }}}
    assert client.put("/api/state", json=saved).status_code == 200
    backup = client.get("/api/backup").json()
    assert backup["state"]["units"]["week-6"]["note"] == "我的中文笔记"
    assert client.put("/api/state", json={"current_unit": "week-0", "units": {}}).status_code == 200
    broken = copy.deepcopy(backup)
    broken["project"]["files"]["../outside.py"] = "bad"
    assert client.post("/api/restore", json=broken).status_code == 422
    assert client.get("/api/state").json()["current_unit"] == "week-0"
    restored = client.post("/api/restore", json=backup)
    assert restored.status_code == 200, restored.text
    assert restored.json()["current_unit"] == "week-6"
    assert list((store.path.parent / "backups").glob("before-restore-*.json"))
    # Reopen SQLite to prove records survive a new store instance.
    assert LearningStore(store.path).state()["units"]["week-6"]["official_note"] == "读题中"


@pytest.mark.parametrize("name", ["../secret.py", "/secret.py", "C:/secret.py", "con.py", "folder/../bad.py", "file.py:stream", "folder./a.py"])
def test_project_rejects_external_and_windows_reserved_paths(name):
    with pytest.raises(ValueError):
        validate_project({"files": {"project.py": "", name: "bad"}, "entrypoint": "project.py"})


def test_multifile_project_runs_tests_and_zip_contains_only_project_files(learning_client):
    client, _ = learning_client
    project = {"entrypoint": "project.py", "files": {
        "project.py": "from helpers import double\ndef main():\n    print(double(5))\nif __name__ == '__main__':\n    main()\n",
        "helpers.py": "def double(n):\n    return n * 2\n",
        "test_project.py": "from helpers import double\ndef test_double():\n    assert double(4) == 8\n",
        "README.md": "测试项目", "requirements.txt": "",
    }}
    assert client.put("/api/project", json=project).status_code == 200
    for route, expected in (("runs", "10"), ("tests", "1 passed")):
        result = client.post(f"/api/project/{route}", json={"interactive": False, "timeout_seconds": 5})
        assert result.status_code == 202, result.text
        until = time.monotonic() + 8
        while time.monotonic() < until:
            run = client.get("/api/runs/" + result.json()["id"]).json()
            if run["status"] in TERMINAL:
                break
            time.sleep(.02)
        assert run["status"] == "completed", run
        assert expected in run["stdout"]
    response = client.get("/api/project/export")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == set(project["files"])
        assert archive.read("README.md").decode("utf-8") == "测试项目"
    checks = client.post("/api/project/check", json={}).json()["checks"]
    assert not next(c for c in checks if c["name"] == "至少三个自定义函数")["passed"]


def test_pytest_syntax_error_cannot_count_as_detecting_a_bug():
    async def check():
        engine = Runner()
        _, _, exercises = load_course()
        try:
            result = await grade_exercise(engine, exercises["week-5-ex-1"], "this is not Python!")
            assert result["passed_count"] == 0
        finally:
            await engine.shutdown()
    asyncio.run(check())


def test_restore_rejects_invalid_failure_message_before_replacing_records(learning_client):
    client, store = learning_client
    _, _, exercises = load_course()
    exercise = exercises["week-0-ex-1"]
    assert client.post("/api/checks", json={"exercise_id": exercise["id"], "code": exercise["wrong_solution"]}).status_code == 200
    backup = client.get("/api/backup").json()
    backup["state"]["current_unit"] = "week-9"
    backup["attempts"][0]["result"]["cases"][0]["message"] = {"invalid": "object"}
    before = store.backup()
    assert client.post("/api/restore", json=backup).status_code == 422
    after = store.backup()
    assert before["state"] == after["state"]
    assert before["attempts"] == after["attempts"]
    assert client.get("/api/state").status_code == 200


def test_learning_contracts_reject_correct_values_with_wrong_structure_or_types():
    async def check():
        engine = Runner()
        _, _, exercises = load_course()
        try:
            result = await grade_exercise(engine, exercises["week-8-ex-2"],
                                          "def to_fahrenheit(celsius):\n    return celsius * 9 / 5 + 32\n")
            assert not result["passed"]
            assert all(case["passed"] for case in result["cases"] if case["name"] != "题面要求的代码结构")
            integer_bools = exercises["week-8-ex-3"]["solution"].replace("return True", "return 1").replace("return False", "return 0")
            result = await grade_exercise(engine, exercises["week-8-ex-3"], integer_bools)
            assert not result["passed"]
            result = await grade_exercise(engine, exercises["week-9-ex-2"],
                "def odd_numbers(stop):\n    return list(range(1, stop, 2))\n\ndef collect_odds(stop):\n    return list(odd_numbers(stop))\n")
            assert not result["passed"]
        finally:
            await engine.shutdown()
    asyncio.run(check())


def test_compressed_backup_restores_history_and_project(learning_client):
    client, store = learning_client
    _, _, exercises = load_course()
    exercise = exercises["week-0-ex-1"]
    result = {"exercise_id": exercise["id"], "passed": False, "passed_count": 0, "total": 1,
              "cases": [{"name": "示例", "passed": False, "message": "请重新检查输出。"}]}
    for _ in range(20):
        store.record(exercise, "# 中文学习记录\n" * 3000, result)
    response = client.get("/api/backup")
    assert response.status_code == 200
    assert response.json()["format"] == "cs50p-workbench-compressed"
    store.save("state", {"current_unit": "week-8", "units": {}})
    restored = client.post("/api/restore", content=response.content, headers={"Content-Type": "application/json"})
    assert restored.status_code == 200, restored.text
    assert restored.json()["current_unit"] == "week-0"
    assert len(store.attempts()) == 20
