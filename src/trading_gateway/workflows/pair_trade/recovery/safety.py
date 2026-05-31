from __future__ import annotations

from typing import Any

from trading_gateway.workflows.pair_trade.planning.helpers import book_top as _book_top
from trading_gateway.workflows.pair_trade.planning.models import PairPlan, PairState, PairTarget
from trading_gateway.workflows.pair_trade.recovery.runtime import client_order_id, remaining
from trading_gateway.support.redaction import redact_mapping, redact_text


def external_open_orders(spot_client: Any, perp_client: Any, plan: PairPlan, pair_id: str) -> list[dict[str, Any]]:
    return _external(spot_client, plan.symbol, "spot", pair_id) + _external(perp_client, plan.perp_symbol, "perp", pair_id)


def capacity_limited_amount(client: Any, plan: PairPlan, leg: str, state: PairState, target: PairTarget, config: Any, leverage: int) -> tuple[float, dict[str, Any]]:
    wanted = remaining(leg, state, target)
    if wanted <= 0:
        return 0.0, {"status": "ok", "amount": 0.0}
    if target.intent == "close" and leg == "spot":
        amount = min(wanted, max(0.0, state.spot_current))
        status = "ok" if amount >= wanted else "reduced" if amount > target.tolerance else "blocked"
        return amount, {"status": status, "leg": leg, "wanted_amount": wanted, "amount": amount, "available_inventory": state.spot_current}
    price = _capacity_price(client, plan.symbol if leg == "spot" else plan.perp_symbol, leg)
    available = _available_quote(leg, state, config)
    multiplier = 1 + config.fee_buffer_bps / 10000
    denominator = price * multiplier / max(1, leverage if leg == "perp" else 1)
    affordable = available / denominator if denominator > 0 else 0.0
    amount = min(wanted, max(0.0, affordable))
    status = "ok" if amount >= wanted else "reduced" if amount > target.tolerance else "blocked"
    return amount, {"status": status, "leg": leg, "wanted_amount": wanted, "amount": amount, "available_quote_usdt": available, "price": price}


def overfill_delta(state: PairState, target: PairTarget) -> dict[str, Any] | None:
    spot_delta = state.spot_current - target.spot_before
    perp_delta = state.perp_short_current - target.perp_before
    if spot_delta > target.target_delta + target.tolerance and spot_delta - perp_delta > target.tolerance:
        return {"overfilled_leg": "spot", "lagging_leg": "perp", "excess_quantity": spot_delta - perp_delta}
    if perp_delta > target.target_delta + target.tolerance and perp_delta - spot_delta > target.tolerance:
        return {"overfilled_leg": "perp", "lagging_leg": "spot", "excess_quantity": perp_delta - spot_delta}
    return None


def overfill_quote(client: Any, plan: PairPlan, leg: str, amount: float) -> float:
    symbol = plan.symbol if leg == "spot" else plan.perp_symbol
    top = _book_top(client, symbol)
    return amount * float(top["ask" if leg == "spot" else "bid"])


def redacted_orders(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe = []
    for row in rows:
        safe.append(redact_mapping({"id": row.get("id"), "symbol": row.get("symbol"), "status": row.get("status"), "side": row.get("side"), "amount": row.get("amount"), "clientOrderId": client_order_id(row)}))
    return safe


def _external(client: Any, symbol: str, leg: str, pair_id: str) -> list[dict[str, Any]]:
    if not hasattr(client, "fetch_open_orders"):
        return []
    try:
        rows = client.fetch_open_orders(symbol) or []
    except Exception as exc:  # noqa: BLE001
        return [{"leg": leg, "symbol": symbol, "status": "audit_unknown", "error": redact_text(exc)}]
    external = []
    for row in rows:
        cid = client_order_id(row)
        if not cid.startswith(pair_id):
            external.append({"leg": leg, **row})
    return external


def _capacity_price(client: Any, symbol: str, leg: str) -> float:
    top = _book_top(client, symbol)
    return float(top["ask" if leg == "spot" else "bid"])


def _available_quote(leg: str, state: PairState, config: Any) -> float:
    reserve = config.spot_quote_reserve_usdt if leg == "spot" else config.perp_margin_reserve_usdt
    free = state.spot_quote_free if leg == "spot" else state.perp_quote_free
    return max(0.0, free - reserve - config.min_free_quote_after_order_usdt)
