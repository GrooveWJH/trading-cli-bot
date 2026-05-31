from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_gateway.workflows.pair_trade.planning.models import PairFinalStatus, PairPlan, PairState, PairTarget
from trading_gateway.app.config import get_gateway_config
from trading_gateway.support.redaction import redact_mapping, redact_text


class PairJournal:
    def __init__(self, pair_id: str, journal_dir: str | Path | None = None) -> None:
        self.pair_id = pair_id
        self.dir = Path(journal_dir or get_gateway_config().pair_execution.journal_dir)
        self.path = self.dir / f"{pair_id}.json"

    def start(self, plan: PairPlan, before: PairState, target: PairTarget) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"pair_id": self.pair_id, "created_at": _now(), "events": []}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self.event("pair_started", "ok", plan=plan.raw, before=before.to_dict(), target=target.to_dict())

    def event(self, name: str, status: str, **fields: Any) -> None:
        self._append({"ts": _now(), "name": name, "status": status, **redact_mapping(fields)})

    def order_intent(self, row: dict[str, Any]) -> None:
        self._append({"ts": _now(), "name": "order_intended", **redact_mapping(row)})

    def order_update(self, client_order_id: str, **fields: Any) -> None:
        self._append({"ts": _now(), "name": "order_updated", "client_order_id": client_order_id, **redact_mapping(fields)})

    def finish(self, final_status: PairFinalStatus, target: dict[str, Any] | None = None) -> None:
        self._append({"ts": _now(), "name": "finalized", "status": str(final_status), "target": redact_mapping(target or {})})

    def read(self) -> dict[str, Any]:
        data = _load_raw(self.path)
        return _replay(data, self.path)

    def _append(self, event: dict[str, Any]) -> None:
        data = _load_raw(self.path)
        data.setdefault("events", []).append(event)
        data["updated_at"] = _now()
        self.path.write_text(json.dumps(redact_mapping(data), indent=2, sort_keys=True), encoding="utf-8")


def load_pair_journal(pair_id: str, journal_dir: str | Path | None = None) -> dict[str, Any]:
    journal = PairJournal(pair_id, journal_dir)
    if not journal.path.exists():
        raise ValueError(f"pair journal not found: {journal.path}")
    return journal.read()


def validate_pair_journal(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("plan"), dict):
        raise ValueError("journal_corrupt: missing pair plan")
    if not isinstance(payload.get("target"), dict):
        raise ValueError("journal_corrupt: missing pair target")
    PairPlan.from_mapping(payload["plan"])
    PairTarget.from_mapping(payload["target"])


def journal_error(exc: BaseException) -> str:
    return redact_text(exc)


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pair_id": path.stem, "created_at": _now(), "events": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("events"), list):
        raise ValueError("journal_corrupt: events must be a list")
    return data


def _replay(data: dict[str, Any], path: Path) -> dict[str, Any]:
    orders: dict[str, dict[str, Any]] = {}
    replayed = {"pair_id": data.get("pair_id") or path.stem, "path": str(path), "events": data.get("events", []), "orders": []}
    for event in data.get("events", []):
        _apply_event(replayed, orders, event)
    replayed["orders"] = list(orders.values())
    validate_pair_journal(replayed)
    return replayed


def _apply_event(replayed: dict[str, Any], orders: dict[str, dict[str, Any]], event: dict[str, Any]) -> None:
    name = event.get("name")
    if name == "pair_started":
        replayed["plan"] = event.get("plan")
        replayed["before"] = event.get("before")
        replayed["target"] = event.get("target")
    elif name == "order_intended":
        orders[str(event["client_order_id"])] = dict(event)
    elif name == "order_updated":
        orders.setdefault(str(event["client_order_id"]), {"client_order_id": event["client_order_id"]}).update(event)
    elif name == "finalized":
        replayed["final_status"] = event.get("status")
        replayed["final_target"] = event.get("target")


def _now() -> str:
    return datetime.now(UTC).isoformat()
