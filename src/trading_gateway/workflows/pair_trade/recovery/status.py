from __future__ import annotations

from typing import Any

from trading_gateway.workflows.pair_trade.journaling.journal import load_pair_journal, validate_pair_journal
from trading_gateway.workflows.pair_trade.planning.models import PairPlan, PairTarget
from trading_gateway.workflows.pair_trade.recovery.runtime import pair_state, pair_target
from trading_gateway.support.redaction import redact_mapping, redact_text


def build_pair_status(spot_client: Any, perp_client: Any, pair_id: str, *, journal_dir: str | None = None) -> dict[str, Any]:
    journal = load_pair_journal(pair_id, journal_dir)
    validate_pair_journal(journal)
    plan = PairPlan.from_mapping(journal["plan"])
    target = PairTarget.from_mapping(journal["target"])
    state = pair_state(spot_client, perp_client, plan)
    restored_orders = []
    for row in journal["orders"]:
        restored_orders.append(_restore_order(_client(row.get("leg"), spot_client, perp_client), row))
    open_orders = _pair_open_orders(spot_client, plan.symbol, pair_id, "spot") + _pair_open_orders(perp_client, plan.perp_symbol, pair_id, "perp")
    target_state = pair_target(state, target)
    final = "pair_target_reached" if _status_reached(target_state) else journal.get("final_status") or "pair_target_not_reached"
    return redact_mapping(
        {
            "mode": "pair_close_status" if plan.intent == "close" else "pair_trading_status",
            "pair_id": pair_id,
            "final_status": final,
            "plan": plan.raw,
            "target": target_state,
            "orders": restored_orders,
            "open_orders": open_orders,
            "suggested_actions": _suggested_actions(pair_id, plan, target_state, open_orders),
            "journal_path": str(journal.get("path") or ""),
        }
    )


def _restore_order(client: Any, row: dict[str, Any]) -> dict[str, Any]:
    symbol = row.get("symbol")
    order_id = row.get("order_id")
    try:
        if order_id:
            found = client.fetch_order(order_id, symbol)
            return {"leg": row.get("leg"), "source": "fetch_order", **found}
    except Exception as exc:  # noqa: BLE001
        return {"leg": row.get("leg"), "source": "fetch_order", "status": "unknown", "error": redact_text(exc), **row}
    return {"leg": row.get("leg"), "source": "journal", **row}


def _pair_open_orders(client: Any, symbol: str | None, pair_id: str, leg: str) -> list[dict[str, Any]]:
    if not symbol or not hasattr(client, "fetch_open_orders"):
        return []
    try:
        rows = client.fetch_open_orders(symbol) or []
    except Exception as exc:  # noqa: BLE001
        return [{"leg": leg, "status": "unknown", "error": redact_text(exc)}]
    return [{"leg": leg, **row} for row in rows if _client_order_id(row).startswith(pair_id)]


def _suggested_actions(pair_id: str, plan: PairPlan, target: dict[str, Any], open_orders: list[dict[str, Any]]) -> list[str]:
    if open_orders:
        return [f"inspect/cancel open orders scoped to pair_id={pair_id} before retrying"]
    if target.get("remaining_quantity", 0) > target.get("tolerance_quantity", 0):
        return [f"rerun pair-status {pair_id} after checking exchange UI", f"manual repair may be needed for {plan.canonical_symbol}"]
    return ["no manual action needed"]


def _status_reached(target: dict[str, Any]) -> bool:
    return bool(target) and target.get("remaining_quantity", 1) <= target.get("tolerance_quantity", 0) and target.get("imbalance_quantity", 1) <= target.get("tolerance_quantity", 0)


def _client(leg: str | None, spot_client: Any, perp_client: Any) -> Any:
    return spot_client if leg == "spot" else perp_client


def _client_order_id(order: dict[str, Any]) -> str:
    raw_info = order.get("info")
    raw_params = order.get("params")
    info = raw_info if isinstance(raw_info, dict) else {}
    params = raw_params if isinstance(raw_params, dict) else {}
    return str(order.get("clientOrderId") or order.get("client_order_id") or params.get("newClientOrderId") or info.get("clientOrderId") or "")
