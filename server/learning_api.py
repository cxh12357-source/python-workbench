"""Course, learning records and checks; learner Python always runs in Runner."""

import ast
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .backup_codec import decode_backup, encode_backup
from .runner import RunnerBusy
from .storage import LearningStore, validate_project, validate_state

ROOT = Path(__file__).resolve().parents[1]


def load_course():
    index = json.loads((ROOT / "data/course-index.json").read_text(encoding="utf-8"))
    content_path = ROOT / "data/learning-content.json"
    if not content_path.exists():
        raise HTTPException(503, "中文课程内容正在准备，请稍后刷新。")
    content = json.loads(content_path.read_text(encoding="utf-8"))
    lessons = {unit["unit_id"]: unit for unit in content["units"]}
    exercises = {ex["id"]: ex for unit in lessons.values() for ex in unit["exercises"]}
    return index, lessons, exercises


def public_lessons(lessons):
    hidden = {"tests", "wrong_solution", "variants", "function_name"}
    return {key: {**unit, "exercises": [{k: v for k, v in ex.items() if k not in hidden}
                                     for ex in unit["exercises"]]}
            for key, unit in lessons.items()}


class CheckRequest(BaseModel):
    exercise_id: str = Field(max_length=100)
    code: str = Field(max_length=100_000)


class ProjectRunRequest(BaseModel):
    stdin: str = Field(default="", max_length=256_000)
    argv: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=50)
    mode: str = "run"
    interactive: bool = True
    timeout_seconds: float = Field(default=120, ge=1, le=300)


async def execute(engine, code=None, **kwargs):
    try:
        run = engine.start(code, **kwargs)
    except RunnerBusy as error:
        raise HTTPException(409, str(error)) from error
    except (RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    await run.task
    return run.snapshot()


def failure_message(run):
    labels = {"timeout": "运行超过 5 秒，请检查循环的结束条件。",
              "output_limit": "输出超过限制，请检查重复打印。",
              "stopped": "检查已停止。", "error": "程序报错，请根据报错信息修改。"}
    return labels.get(run["status"], "结果与预期不同。") + ("\n" + run["stderr"][-1500:] if run["stderr"] else "")


def json_equal(actual, expected):
    """Preserve booleans inside collections while accepting equivalent numeric values."""
    if type(actual) in {int, float} and type(expected) in {int, float}:
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(json_equal(a, b) for a, b in zip(actual, expected))
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(json_equal(actual[k], expected[k]) for k in actual)
    return actual == expected


def structure_cases(exercise, code):
    rule = exercise.get("required_structure")
    if not rule:
        return []
    try:
        tree = ast.parse(code)
        if "class" in rule:
            node = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == rule["class"]), None)
            methods = {item.name: item for item in node.body if isinstance(item, ast.FunctionDef)} if node else {}
            passed = node is not None and set(rule["methods"]).issubset(methods)
            if passed and "property" in rule:
                passed = any((isinstance(d, ast.Name) and d.id == "property") or (isinstance(d, ast.Attribute) and d.attr == "property")
                             for d in methods[rule["property"]].decorator_list)
        elif "function" in rule:
            node = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == rule["function"]), None)
            classes = (ast.Yield, ast.YieldFrom) if rule["node"] == "Yield" else (ast.ListComp,)
            passed = node is not None and any(isinstance(child, classes) for child in ast.walk(node))
        elif "import" in rule:
            passed = any((isinstance(node, ast.Import) and any(alias.name == rule["import"] for alias in node.names))
                         or (isinstance(node, ast.ImportFrom) and node.module == rule["import"]) for node in ast.walk(tree))
        else:
            passed = False
    except SyntaxError:
        passed = False
    return [{"name": "题面要求的代码结构", "passed": bool(passed),
             "message": "代码包含题面要求的结构；行为还需通过下面的案例。" if passed else exercise["structure_message"]}]


async def grade_exercise(engine, exercise, code):
    cases = structure_cases(exercise, code)
    kind = exercise["kind"]
    fixtures = exercise.get("files", {})
    if kind == "pytest":
        for variant in exercise["variants"]:
            files = {**fixtures, **variant["files"], "test_student.py": code}
            run = await execute(engine, files=files, entrypoint="test_student.py", pytest_mode=True,
                                argv=["-q", "test_student.py"], timeout=5)
            # Only assertion failures prove a bug was caught. Import/syntax/no-tests failures don't.
            caught_bug = run["exit_code"] == 1 and "failed" in run["stdout"] and "ERROR collecting" not in run["stdout"]
            success = run["status"] == "completed" if variant["should_pass"] else caught_bug
            cases.append({"name": variant["name"], "passed": bool(success),
                          "message": "测试正确区分了这个实现。" if success else
                          ("正确实现应通过测试，错误实现应触发断言失败。\n" + run["stdout"][-1500:] + run["stderr"][-500:])})
    elif kind in {"stdout", "function"}:
        for case in exercise["tests"]:
            if kind == "stdout":
                run = await execute(engine, code, stdin=case.get("stdin", ""), argv=case.get("argv", []),
                                    files=fixtures, timeout=5)
                actual = run["stdout"].replace("\r\n", "\n")
                expected = case["expected"].replace("\r\n", "\n")
                success = run["status"] == "completed" and actual == expected
            else:
                name = exercise["function_name"]
                args = json.dumps(case.get("args", []), ensure_ascii=False)
                harness = (
                    "import json, runpy\n"
                    "namespace = runpy.run_path('student.py', run_name='__student__')\n"
                    f"function = namespace[{name!r}]\n"
                    f"result = function(*json.loads({args!r}))\n"
                    "print('WORKBENCH_RESULT:' + json.dumps(result, ensure_ascii=False, allow_nan=False))\n"
                )
                run = await execute(engine, harness, files={**fixtures, "student.py": code}, entrypoint="_check.py", timeout=5)
                lines = [line.partition("WORKBENCH_RESULT:")[2] for line in run["stdout"].splitlines() if line.startswith("WORKBENCH_RESULT:")]
                actual, expected = None, case["expected"]
                try:
                    actual = json.loads(lines[-1]) if lines else None
                    if "approx" in case and type(actual) in {int, float} and type(expected) in {int, float}:
                        equal = math.isclose(actual, expected, rel_tol=0, abs_tol=case["approx"])
                    else:
                        equal = json_equal(actual, expected)
                    success = run["status"] == "completed" and bool(lines) and equal
                except (ValueError, TypeError):
                    success = False
                actual, expected = json.dumps(actual, ensure_ascii=False), json.dumps(expected, ensure_ascii=False)
            cases.append({"name": case["name"], "passed": bool(success), "expected": expected,
                          "actual": actual, "message": "这个案例通过了。" if success else failure_message(run)})
    else:
        raise HTTPException(500, "题目检查方式不受支持。")
    if not cases:
        raise HTTPException(500, "题目尚未配置检查案例。")
    passed_count = sum(case["passed"] for case in cases)
    return {"exercise_id": exercise["id"], "passed": passed_count == len(cases),
            "passed_count": passed_count, "total": len(cases), "cases": cases}


def project_checks(project):
    files = project["files"]
    checks = []
    def add(name, passed, message):
        checks.append({"name": name, "passed": bool(passed), "message": message})
    try:
        tree = ast.parse(files.get("project.py", ""))
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        names = {node.name for node in functions}
        def is_stub(node):
            body = [line for line in node.body if not (isinstance(line, ast.Expr) and isinstance(line.value, ast.Constant) and isinstance(line.value.value, str))]
            return not body or all(isinstance(line, ast.Pass) or (
                isinstance(line, ast.Raise) and isinstance(line.exc, (ast.Name, ast.Call))
                and (line.exc.id if isinstance(line.exc, ast.Name) else getattr(line.exc.func, "id", "")) == "NotImplementedError"
            ) for line in body)
        implemented = [node for node in functions if node.name != "main" and not is_stub(node)]
        add("project.py 与 main", "project.py" in files and "main" in names,
            "官方要求 project.py 中定义 main 函数。")
        add("至少三个自定义函数", len(implemented) >= 3,
            "除 main 外，至少写三个自己的顶层函数；检查仅判断结构。")
    except SyntaxError as error:
        add("Python 语法", False, f"project.py 第 {error.lineno} 行：{error.msg}")
    try:
        tests = ast.parse(files.get("test_project.py", ""))
        test_names = {node.name for node in tests.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}
        matching = sum(f"test_{node.name}" in test_names for node in functions if node.name != "main") if 'functions' in locals() else 0
        add("测试函数", "test_project.py" in files and matching >= 3,
            "在 test_project.py 中为至少三个自定义函数写对应测试，随后运行 pytest 检查行为。")
    except SyntaxError as error:
        add("测试语法", False, f"test_project.py 第 {error.lineno} 行：{error.msg}")
    readme = files.get("README.md", "")
    add("项目说明", len(readme.strip()) >= 200 and "请写下你自己的想法" not in readme,
        "README 应说明项目目标、文件、运行方法与设计选择。这里仅做初步长度检查，请自行核对内容。")
    add("依赖文件", "requirements.txt" in files, "记录第三方依赖；不使用第三方包时可留空。安装新依赖需要在项目环境中单独完成。")
    add("演示准备", "http" in readme and any(word in readme.lower() for word in ("video", "视频", "演示")),
        "在项目说明中记录自己的演示视频链接；本地检查不验证视频或官方提交。")
    return {"checks": checks}


def create_learning_router(engine, authorize, store=None):
    store = store or LearningStore()
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @router.get("/course")
    def course():
        index, lessons, _ = load_course()
        return {"index": index, "lessons": public_lessons(lessons)}

    @router.get("/state")
    def state():
        return store.state()

    @router.put("/state")
    def save_state(value: dict):
        try:
            store.save("state", validate_state(value))
            return store.state()
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/checks")
    async def check(value: CheckRequest):
        _, _, exercises = load_course()
        if value.exercise_id not in exercises:
            raise HTTPException(404, "练习不存在。")
        exercise = exercises[value.exercise_id]
        result = await grade_exercise(engine, exercise, value.code)
        result["attempt_id"] = store.record(exercise, value.code, result)
        return result

    @router.get("/project")
    def project():
        return store.document("project")

    @router.put("/project")
    def save_project(value: dict):
        try:
            return store.save("project", validate_project(value))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/project/check")
    def check_project():
        return project_checks(store.document("project"))

    def start_project(value, test=False):
        project = store.document("project")
        entrypoint = "test_project.py" if test else project["entrypoint"]
        if test and entrypoint not in project["files"]:
            raise HTTPException(422, "请先创建 test_project.py 并为自己的函数写测试。")
        try:
            run = engine.start(None, stdin=value.stdin, argv=value.argv,
                               files=project["files"], entrypoint=entrypoint,
                               interactive=value.interactive and not test,
                               timeout=value.timeout_seconds if not test else min(value.timeout_seconds, 30),
                               pytest_mode=test)
            return run.snapshot()
        except RunnerBusy as error:
            raise HTTPException(409, str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/project/runs", status_code=202)
    async def run_project(value: ProjectRunRequest):
        return start_project(value, test=value.mode == "test")

    @router.post("/project/tests", status_code=202)
    async def test_project(value: ProjectRunRequest):
        return start_project(value, test=True)

    @router.get("/project/export")
    def export_project():
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in store.document("project")["files"].items():
                archive.writestr(path, content.encode("utf-8"))
        return Response(stream.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="my-python-project.zip"'})

    @router.get("/backup")
    def backup():
        try:
            value = store.backup()
            if len(value["attempts"]) > 100_000:
                raise ValueError("练习历史超过 10 万次，请保留 local-data 文件夹作为完整档案。")
            return Response(encode_backup(value), media_type="application/json",
                            headers={"Content-Disposition": 'attachment; filename="python-workbench-backup.json"'})
        except ValueError as error:
            raise HTTPException(413, str(error)) from error

    @router.post("/restore")
    def restore(value: dict):
        _, _, exercises = load_course()
        try:
            return store.restore(decode_backup(value), exercises)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from error

    return router
