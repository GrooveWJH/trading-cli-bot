#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from importlib.util import find_spec
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != SCRIPT_DIR]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if "TG_CLI_START_TS" not in os.environ:
    os.environ["TG_CLI_START_TS"] = str(time.time())


def _ensure_project_python() -> None:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists() or Path(sys.executable).resolve() == venv_python.resolve():
        return
    if find_spec("ccxt") is None or find_spec("typer") is None:
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


_ensure_project_python()

from trading_gateway.interfaces.cli.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
