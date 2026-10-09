"""This file only runs inside the disposable learner subprocess."""

import runpy
import sys


def main():
    # The parent sends this line ONLY after attaching this process to its Job.
    # It is consumed before user code, so it never becomes learner stdin.
    if sys.stdin.buffer.readline() != b"PYTHON_WORKBENCH_START\n":
        raise SystemExit(125)
    mode, script = sys.argv[1:3]
    from pathlib import Path
    # Project imports work just as they do from a normal local Python command.
    sys.path.insert(0, str(Path.cwd()))
    if mode == "pytest":
        sys.argv = ["pytest", "-q", script]
        runpy.run_module("pytest", run_name="__main__")
    else:
        sys.argv = [script, *sys.argv[3:]]
        sys.path.insert(0, str(Path(script).parent))
        runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
