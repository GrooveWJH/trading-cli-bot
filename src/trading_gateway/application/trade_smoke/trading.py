from __future__ import annotations

from typing import Any

from trading_gateway.domain.models import OrderIntent
from trading_gateway.application.trade_smoke.planning import build_order_plan, validate_live_request
from trading_gateway.support.redaction import redact_mapping


def _opposite(side: str) -> str:
    return "sell" if side == "buy" else "buy"


def _prepare_swap(client: Any, intent: OrderIntent) -> None:
    set_margin = getattr(client, "set_margin_mode", None)
    if callable(set_margin):
        set_margin(intent.margin_mode, intent.symbol)
    set_leverage = getattr(client, "set_leverage", None)
    if callable(set_leverage):
        set_leverage(int(intent.leverage), intent.symbol)


def _open_order(client: Any, intent: OrderIntent, plan: Any) -> dict[str, Any]:
    if plan.order_method == "create_market_buy_order_with_cost":
        return client.create_market_buy_order_with_cost(intent.symbol, plan.cost_amount, plan.params)
    return client.create_order(intent.symbol, "market", intent.side, plan.amount, None, plan.params)


def run_trade_smoke(
    client: Any,
    intent: OrderIntent,
    *,
    live: bool,
    confirm: str,
    close_after: bool = True,
    last_price: float | None = None,
) -> dict[str, Any]:
    validate_live_request(intent, live=live, confirm=confirm)
    plan = build_order_plan(client, intent, last_price=last_price)
    if not live:
        return {"status": "dry_run", "plan": plan.to_dict(), "confirm": plan.live_confirm_phrase}
    if intent.market == "swap":
        _prepare_swap(client, intent)
    opened = _open_order(client, intent, plan)
    closed: dict[str, Any] | None = None
    if close_after:
        close_amount = float(opened.get("filled") or opened.get("amount") or plan.amount)
        close_params = {"reduceOnly": True} if intent.market == "swap" else {}
        closed = client.create_order(intent.symbol, "market", _opposite(intent.side), close_amount, None, close_params)
    return redact_mapping({"status": "live", "plan": plan.to_dict(), "opened": opened, "closed": closed})
