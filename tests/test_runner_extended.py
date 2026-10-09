import time

from fastapi.testclient import TestClient

from server.app import create_app
from server.runner import ROOT, Runner
from test_runner import BOOTSTRAP, ORIGIN, await_output, launch, wait


def browser():
    client = TestClient(create_app(), base_url=ORIGIN)
    return client


def authenticate(client):
    session = client.get("/api/session", headers=BOOTSTRAP)
    client.headers["X-Runner-Token"] = session.json()["token"]


def test_interactive_inputs_blank_and_eof():
    with browser() as client:
        authenticate(client)
        response = client.post("/api/runs", json={
            "code": "print('开始',flush=True)\na=input('姓名: ')\nb=input('空行: ')\nprint(repr(a),repr(b))\nprint(input())",
            "interactive": True,
        })
        assert response.status_code == 202
        run_id = response.json()["id"]
        assert response.json()["timeout_seconds"] == 120
        result = await_output(client, run_id, "姓名: ")
        assert result["status"] == "running" and result["input_open"]
        assert client.post(f"/api/runs/{run_id}/input", json={"text": "学习者"}).status_code == 200
        await_output(client, run_id, "空行: ")
        assert client.post(f"/api/runs/{run_id}/input", json={"text": ""}).status_code == 200
        await_output(client, run_id, "'学习者' ''")
        assert client.post(f"/api/runs/{run_id}/input", json={"eof": True}).status_code == 200
        result = wait(client, run_id)
        assert result["status"] == "error" and "EOFError" in result["stderr"]
        assert not result["input_open"]
        assert client.post(f"/api/runs/{run_id}/input", json={"text": "late"}).status_code == 409


def test_interactive_prefill_and_successful_exit():
    with browser() as client:
        authenticate(client)
        result = client.post("/api/runs", json={
            "code": "print(input(),input())", "stdin": "预填\n", "interactive": True,
        }).json()
        run_id = result["id"]
        assert client.post(f"/api/runs/{run_id}/input", json={"text": "后续"}).status_code == 200
        final = wait(client, run_id)
        assert final["status"] == "completed"
        assert final["stdout"] == "预填 后续\r\n"


def test_interactive_time_limit_validation():
    with browser() as client:
        authenticate(client)
        assert client.post("/api/runs", json={"code": "pass", "interactive": True, "timeout": 9}).status_code == 422
        assert client.post("/api/runs", json={"code": "pass", "interactive": True, "timeout": 301}).status_code == 422


def test_multi_file_import_and_csv_and_pillow():
    with browser() as client:
        authenticate(client)
        response = client.post("/api/runs", json={
            "files": {
                "app/main.py": "import helper,csv\nfrom PIL import Image\nprint(helper.answer)\nprint(list(csv.reader(open('table.csv',encoding='utf-8'))))\nprint(Image.new('RGB',(2,3)).size)",
                "app/helper.py": "answer=42", "table.csv": "姓名,课程\n学习者,CS50P\n",
            }, "entrypoint": "app/main.py",
        })
        assert response.status_code == 202, response.text
        result = wait(client, response.json()["id"])
        assert result["status"] == "completed", result
        assert "42\r\n" in result["stdout"]
        assert "学习者" in result["stdout"] and "(2, 3)" in result["stdout"]


def test_controlled_pytest_entrypoint():
    with browser() as client:
        authenticate(client)
        response = client.post("/api/runs", json={
            "files": {"project.py": "def add(a,b): return a+b",
                      "test_project.py": "from project import add\ndef test_add(): assert add(2,3)==5"},
            "entrypoint": "test_project.py", "pytest_mode": True,
        })
        assert response.status_code == 202
        result = wait(client, response.json()["id"])
        assert result["status"] == "completed", result
        assert "1 passed" in result["stdout"]


def test_code_becomes_harness_entrypoint_with_fixtures():
    with browser() as client:
        authenticate(client)
        response = client.post("/api/runs", json={
            "code": "import student\nprint(student.value)",
            "files": {"student.py": "value=123", "_check.py": "raise RuntimeError('must overwrite')"},
            "entrypoint": "_check.py",
        })
        assert response.status_code == 202
        result = wait(client, response.json()["id"])
        assert result["status"] == "completed" and result["stdout"] == "123\r\n"


def test_invalid_project_paths_and_duplicates_rejected():
    with browser() as client:
        authenticate(client)
        for name in ("../outside.py", "C:/outside.py", "/outside.py", "x/../../outside.py",
                     "NUL.py", "file.py:alternate", "x/./main.py", "bad .", "x\x01.py"):
            response = client.post("/api/runs", json={"files": {name: "pass"}, "entrypoint": name})
            assert response.status_code == 422, (name, response.text)
        response = client.post("/api/runs", json={"files": {"A.py": "pass", "a.py": "pass"}, "entrypoint": "A.py"})
        assert response.status_code == 422


def test_learning_interpreter_is_native_not_windows_store_alias():
    with browser() as client:
        authenticate(client)
        result = wait(client, launch(client, "import sys\nprint(sys._base_executable)"))
        assert result["status"] == "completed"
        assert "Microsoft\\WindowsApps" not in result["stdout"]
