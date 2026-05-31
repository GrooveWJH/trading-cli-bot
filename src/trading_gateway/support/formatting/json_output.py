from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trading_gateway.support.redaction import redact_mapping


def print_json(payload: Any) -> None:
    print(json.dumps(redact_mapping(payload), ensure_ascii=False, indent=2, sort_keys=True))


def write_report(report_dir: str | Path | None, name: str, payload: Any) -> Path | None:
    if not report_dir:
        return None
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    target.write_text(json.dumps(redact_mapping(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return target
