import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, Field

from .runner import Runner, RunnerBusy

BASE = Path(__file__).resolve().parent


class RunRequest(BaseModel):
    code: str | None = Field(default=None, max_length=100_000)
    stdin: str = Field(default="", max_length=256_000)
    argv: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=50)
    interactive: bool = False
    timeout: float | None = Field(default=None, ge=1, le=300,
                                validation_alias=AliasChoices("timeout_seconds", "timeout"))
    files: dict[str, str] | None = None
    entrypoint: str = "main.py"
    pytest_mode: bool = False


class InputRequest(BaseModel):
    text: str = Field(default="", max_length=100_000)
    eof: bool = False


def create_app(runner=None, port=8765, store=None):
    engine = runner or Runner()
    token = secrets.token_urlsafe(32)
    origin = f"http://127.0.0.1:{port}"
    host = f"127.0.0.1:{port}"

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.shutdown()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runner = engine

    @app.middleware("http")
    async def same_origin(request, call_next):
        # Exact Host blocks DNS rebinding. No wildcard CORS policy is installed.
        if request.headers.get("host") != host:
            return JSONResponse({"detail": "仅接受本机工作台地址。"}, status_code=403)
        supplied_origin = request.headers.get("origin")
        if supplied_origin is not None and supplied_origin != origin:
            return JSONResponse({"detail": "来源地址不允许。"}, status_code=403)
        if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            return JSONResponse({"detail": "请从工作台页面发起请求。"}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            if length is None:
                return JSONResponse({"detail": "请求需包含 Content-Length。"}, status_code=411)
            try:
                large_write = request.url.path == "/api/restore" or (
                    request.method == "PUT" and request.url.path in {"/api/state", "/api/project"}
                )
                limit = 8_388_608 if large_write else 1_048_576
                if not 0 <= int(length) <= limit:
                    raise ValueError
            except ValueError:
                return JSONResponse({"detail": "请求内容过大。"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; "
            "connect-src 'self'; frame-src https://player.bilibili.com https://www.youtube.com "
            "https://www.youtube-nocookie.com https://video.cs50.io; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        return response

    def authorized(request: Request):
        candidate = request.headers.get("x-runner-token", "")
        if not secrets.compare_digest(candidate, token):
            raise HTTPException(403, "会话未授权，请重新打开本机工作台页面。")

    app.state.authorize = authorized
    from .learning_api import create_learning_router
    app.include_router(create_learning_router(engine, authorized, store))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/session")
    async def session(request: Request):
        # Browser same-origin fetch sets Sec-Fetch-Site. A custom header prevents
        # cross-origin simple requests from reading/bootstraping a session.
        if (request.headers.get("sec-fetch-site") != "same-origin"
                or request.headers.get("x-runner-bootstrap") != "1"):
            raise HTTPException(403, "请从本机工作台页面初始化会话。")
        return {"token": token, "timeout_seconds": engine.timeout,
                "output_limit_bytes": engine.output_limit}

    @app.post("/api/runs", dependencies=[Depends(authorized)], status_code=202)
    async def start(payload: RunRequest):
        if payload.interactive and payload.timeout is not None and payload.timeout < 10:
            raise HTTPException(422, "交互运行时限为 10 至 300 秒。")
        try:
            run = engine.start(payload.code, payload.stdin, payload.argv,
                               interactive=payload.interactive, timeout=payload.timeout,
                               files=payload.files, entrypoint=payload.entrypoint,
                               pytest_mode=payload.pytest_mode)
        except RunnerBusy as error:
            raise HTTPException(409, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return run.snapshot()

    def find(run_id):
        if run_id not in engine.runs:
            raise HTTPException(404, "找不到本次运行。")
        return engine.runs[run_id]

    @app.get("/api/runs/{run_id}", dependencies=[Depends(authorized)])
    async def status(run_id: str):
        return find(run_id).snapshot()

    @app.delete("/api/runs/{run_id}", dependencies=[Depends(authorized)])
    async def stop(run_id: str):
        run = find(run_id)
        run.request_stop()
        return run.snapshot()

    @app.post("/api/runs/{run_id}/input", dependencies=[Depends(authorized)])
    async def send_input(run_id: str, payload: InputRequest):
        find(run_id)
        try:
            run = engine.send_input(run_id, payload.text, payload.eof)
        except RunnerBusy as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return run.snapshot()

    @app.get("/api/runs/{run_id}/artifacts/{path:path}", dependencies=[Depends(authorized)])
    async def download_artifact(run_id: str, path: str):
        run = find(run_id)
        with run.lock:
            artifact = run.artifacts.get(path)
        if artifact is None:
            raise HTTPException(404, "该运行产物不存在或已从会话内存清理。")
        filename = quote(path.split("/")[-1], safe="")
        return Response(artifact.data, media_type=artifact.mime,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

    dist = BASE.parent / "web/dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    async def home():
        return FileResponse(dist / "index.html" if (dist / "index.html").is_file()
                            else BASE / "static/index.html")

    @app.get("/runner-probe")
    async def probe():
        return FileResponse(BASE / "static/index.html")

    @app.get("/favicon.svg")
    async def favicon():
        path = dist / "favicon.svg"
        if not path.is_file():
            raise HTTPException(404, "图标尚未构建。")
        return FileResponse(path, media_type="image/svg+xml")

    @app.get("/console.js")
    async def console_script():
        return FileResponse(BASE / "static/console.js", media_type="text/javascript")

    @app.get("/console.css")
    async def console_styles():
        return FileResponse(BASE / "static/console.css", media_type="text/css")

    return app


app = create_app(port=int(os.environ.get("PYTHON_WORKBENCH_PORT", "8765")))
