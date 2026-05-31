from __future__ import annotations

from typing import Any

from trading_gateway.adapters.exchanges.fees import fee_report
from trading_gateway.support.redaction import redact_mapping


def build_single_leg_report(plan: dict[str, Any], steps: list[dict[str, Any]], final_status: str, target: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"mode": "single_leg_run", "final_status": final_status, "plan": plan, "steps": steps, "fees": fee_report(plan, steps)}
    if target is not None:
        payload["target"] = target
    if is_perp_close_all(plan):
        payload = compact_close_all_report(payload)
    return redact_mapping(payload)


def is_perp_close_all(plan: dict[str, Any]) -> bool:
    return plan.get("market") == "perp" and str(plan.get("quantity")).upper() == "ALL"


def compact_close_all_report(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    compact["steps"] = [compact_close_all_step(row) for row in payload.get("steps") or []]
    target = payload.get("target")
    if isinstance(target, dict):
        compact["target"] = compact_close_all_target(target)
    return compact


def compact_close_all_step(row: dict[str, Any]) -> dict[str, Any]:
    compact = dict(row)
    positions = compact.pop("positions", None)
    if isinstance(positions, list):
        compact["position_count"] = len(positions)
    open_orders = compact.pop("open_orders", None)
    if isinstance(open_orders, list):
        compact["open_order_count"] = len(open_orders)
    return compact


def compact_close_all_target(target: dict[str, Any]) -> dict[str, Any]:
    compact = dict(target)
    open_orders = compact.pop("open_close_orders", None)
    if isinstance(open_orders, list):
        compact["open_close_order_ids"] = [row.get("id") for row in open_orders if isinstance(row, dict) and row.get("id")]
    return compact
