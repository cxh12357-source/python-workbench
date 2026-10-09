from fastapi.testclient import TestClient

from server.app import create_app
from server.storage import LearningStore
from test_runner import BOOTSTRAP, ORIGIN, launch, wait


def authenticate(client):
    client.headers["X-Runner-Token"] = client.get("/api/session", headers=BOOTSTRAP).json()["token"]


def test_real_png_text_and_changed_fixture_artifacts(tmp_path):
    with TestClient(create_app(store=LearningStore(tmp_path / "learning.db")), base_url=ORIGIN) as client:
        authenticate(client)
        result = client.post("/api/runs", json={
            "code": "from pathlib import Path\nfrom PIL import Image\nImage.new('RGB',(8,6),'red').save('result.png')\nPath('new.txt').write_text('中文产物',encoding='utf-8')\nPath('change.txt').write_text('修改后',encoding='utf-8')",
            "files": {"change.txt": "修改前", "unchanged.txt": "原始资料"},
        })
        assert result.status_code == 202
        run_id = result.json()["id"]
        final = wait(client, run_id)
        assert final["status"] == "completed"
        items = {item["name"]: item for item in final["artifacts"]}
        assert set(items) == {"result.png", "new.txt", "change.txt"}
        assert items["result.png"]["mime"] == "image/png"
        image = client.get(f"/api/runs/{run_id}/artifacts/result.png")
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert image.headers["content-type"] == "image/png"
        assert image.headers["content-disposition"].startswith("attachment;")
        assert client.get(f"/api/runs/{run_id}/artifacts/new.txt").content.decode("utf-8") == "中文产物"
        assert client.get(f"/api/runs/{run_id}/artifacts/unchanged.txt").status_code == 404
        assert client.get(f"/api/runs/{run_id}/artifacts/result.png", headers={"X-Runner-Token": "bad"}).status_code == 403


def test_artifact_limits_and_cache_exclusions(tmp_path):
    with TestClient(create_app(store=LearningStore(tmp_path / "learning.db")), base_url=ORIGIN) as client:
        authenticate(client)
        code = (
            "from pathlib import Path\n"
            "Path('oversize.txt').write_bytes(b'x'*1048577)\n"
            "Path('__pycache__').mkdir(exist_ok=True)\n"
            "Path('__pycache__/ignore.txt').write_text('ignore')\n"
            "for i in range(30): Path(f'{i:02}.txt').write_bytes(b'a'*60000)\n"
        )
        result = wait(client, launch(client, code))
        assert result["status"] == "completed"
        assert 1 <= len(result["artifacts"]) <= 20
        assert sum(item["size"] for item in result["artifacts"]) <= 1048576
        assert all(item["name"] != "oversize.txt" and "__pycache__" not in item["name"]
                   for item in result["artifacts"])


def test_junction_to_outside_directory_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("must not be collected", encoding="utf-8")
    code = (
        "import subprocess,os\n"
        f"p=subprocess.run(['cmd.exe','/c','mklink','/J','outside-link',{str(outside)!r}],capture_output=True)\n"
        "print(p.returncode)\n"
        "print(os.path.exists('outside-link/secret.txt'))\n"
    )
    with TestClient(create_app(store=LearningStore(tmp_path / "learning.db")), base_url=ORIGIN) as client:
        authenticate(client)
        run_id = launch(client, code)
        result = wait(client, run_id)
        assert result["status"] == "completed"
        assert result["stdout"] == "0\r\nTrue\r\n", result
        assert not result["artifacts"]
        assert client.get(f"/api/runs/{run_id}/artifacts/outside-link/secret.txt").status_code == 404
        assert (outside / "secret.txt").read_text(encoding="utf-8") == "must not be collected"


def test_artifact_history_is_bounded_to_twenty_runs(tmp_path):
    with TestClient(create_app(store=LearningStore(tmp_path / "learning.db")), base_url=ORIGIN) as client:
        authenticate(client)
        ids = []
        for _ in range(21):
            run_id = launch(client, "from pathlib import Path\nPath('result.txt').write_text('result')")
            ids.append(run_id)
            assert wait(client, run_id)["status"] == "completed"
        assert client.get(f"/api/runs/{ids[0]}/artifacts/result.txt").status_code == 404
        assert client.get(f"/api/runs/{ids[-1]}/artifacts/result.txt").status_code == 200
        assert len([run for run in client.app.state.runner.runs.values() if run.artifacts]) == 20
