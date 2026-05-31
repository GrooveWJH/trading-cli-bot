from __future__ import annotations

import time
import uuid
from typing import Any

from trading_gateway.adapters.exchanges.order_params import build_pair_order_params
from trading_gateway.adapters.exchanges.rules import amount_to_precision
from trading_gateway.adapters.exchanges.single_leg import adapter_for
from trading_gateway.workflows.pair_trade.journaling.journal import PairJournal, journal_error
from trading_gateway.workflows.pair_trade.planning.helpers import book_top as _book_top
from trading_gateway.workflows.pair_trade.planning.models import PairFinalStatus, PairPlan
from trading_gateway.workflows.pair_trade.recovery.runtime import client_order_id as _cid
from trading_gateway.workflows.pair_trade.recovery.runtime import is_maker_reject, is_unknown_submit
from trading_gateway.app.config import get_gateway_config
from trading_gateway.support.redaction import redact_text


def submit_leg(
    client: Any,
    plan: PairPlan,
    leg: str,
    amount: float,
    pair_id: str,
    attempt: int,
    journal: PairJournal,
    *,
    side: str | None = None,
    post_only: bool = True,
    reduce_only: bool = False,
) -> tuple[PairFinalStatus | str, dict[str, Any] | None]:
    exchange = plan.spot_exchange if leg == "spot" else plan.perp_exchange
    market = "spot" if leg == "spot" else "perp"
    adapter = adapter_for(exchange, market)
    symbol = plan.symbol if leg == "spot" else plan.perp_symbol
    order_side = side or _default_side(plan, leg)
    amount = _order_amount(adapter, client, symbol, amount, plan)
    price = _price(adapter, client, symbol, leg, order_side, post_only)
    order_type = _order_type(adapter, post_only)
    client_order_id = f"{pair_id}_{leg}_{uuid.uuid4().hex[:6]}"
    params = order_params(adapter, client, leg, client_order_id, post_only=post_only, reduce_only=reduce_only)
    journal.order_intent({"leg": leg, "symbol": symbol, "side": order_side, "amount": amount, "client_order_id": client_order_id, "attempt": attempt, "status": "intent"})
    try:
        order = client.create_order(symbol, order_type, order_side, amount, price, params)
    except Exception as exc:  # noqa: BLE001
        status = "submit_unknown" if is_unknown_submit(exc) else "rejected" if is_maker_reject(exc) else "submit_error"
        journal.order_update(client_order_id, status=status, error=journal_error(exc))
        if status == "submit_unknown":
            restored = restore_order(client, symbol, client_order_id=client_order_id, pair_id=pair_id)
            if restored:
                journal.order_update(client_order_id, status=restored.get("status"), order_id=restored.get("id"))
                return "ok", restored
            return PairFinalStatus.ORDER_STATE_UNKNOWN, None
        return (status, None) if status == "rejected" else (PairFinalStatus.SUBMIT_ERROR, None)
    order.setdefault("clientOrderId", client_order_id)
    order.setdefault("params", params)
    journal.order_update(client_order_id, status=order.get("status", "open"), order_id=order.get("id"))
    return "ok", order


def order_params(adapter: Any, client: Any, leg: str, client_order_id: str, *, post_only: bool = True, reduce_only: bool = False) -> dict[str, Any]:
    return build_pair_order_params(
        adapter,
        client,
        leg,
        client_order_id,
        post_only=post_only,
        reduce_only=reduce_only,
    )


def monitor_order(client: Any, order: dict[str, Any], symbol: str, timeout_sec: float, poll_interval_sec: float, pair_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + max(0, timeout_sec)
    while True:
        try:
            status = client.fetch_order(order["id"], symbol)
        except Exception as exc:  # noqa: BLE001
            restored = restore_order(client, symbol, order_id=order.get("id"), client_order_id=_cid(order), pair_id=pair_id)
            return restored or {"id": order.get("id"), "status": "unknown", "error": redact_text(exc)}
        if status.get("status") in {"closed", "canceled", "rejected", "expired"} or time.monotonic() >= deadline:
            return status
        time.sleep(min(poll_interval_sec, max(0.0, deadline - time.monotonic())))


def cancel_order(client: Any, symbol: str, order: dict[str, Any], steps: list[dict[str, Any]], progress: Any, leg: str, journal: PairJournal, pair_id: str) -> bool:
    if not _cid(order).startswith(pair_id):
        return False
    last: dict[str, Any] = {}
    for _ in range(max(1, get_gateway_config().pair_execution.cancel_retry_count)):
        try:
            last = client.cancel_order(order["id"], symbol)
            _emit(steps, progress, {"name": "cancel_open_orders", "status": last.get("status", "submitted"), "leg": leg, "order_id": order.get("id")})
            verify = client.fetch_order(order["id"], symbol)
            _emit(steps, progress, {"name": "cancel_verify", "status": verify.get("status"), "leg": leg, "order_id": order.get("id")})
            journal.order_update(_cid(order), status=verify.get("status"), order_id=order.get("id"))
            return verify.get("status") in {"canceled", "closed", "expired", "rejected"}
        except Exception as exc:  # noqa: BLE001
            last = {"status": "unknown", "error": redact_text(exc)}
            restored = restore_order(client, symbol, order_id=order.get("id"), client_order_id=_cid(order), pair_id=pair_id)
            if restored:
                status = str(restored.get("status") or "unknown")
                _emit(steps, progress, {"name": "cancel_verify", "status": status, "leg": leg, "order_id": order.get("id"), "restored": True})
                journal.order_update(_cid(order), status=status, order_id=order.get("id"))
                return status in {"canceled", "closed", "expired", "rejected"}
    _emit(steps, progress, {"name": "cancel_verify", "status": "unknown", "leg": leg, "order_id": order.get("id"), **last})
    return False


def restore_order(client: Any, symbol: str, *, pair_id: str, order_id: str | None = None, client_order_id: str | None = None) -> dict[str, Any] | None:
    for _ in range(max(1, get_gateway_config().pair_execution.order_lookup_retry_count)):
        if order_id:
            try:
                return client.fetch_order(order_id, symbol)
            except Exception:  # noqa: BLE001
                pass
        try:
            for row in client.fetch_open_orders(symbol) or []:
                if _cid(row) == client_order_id or _cid(row).startswith(pair_id):
                    return row
        except Exception:  # noqa: BLE001
            pass
    return None


def _price(adapter: Any, client: Any, symbol: str, leg: str, side: str, post_only: bool) -> float | None:
    if leg == "spot":
        return adapter.maker_price(client, symbol, side, {"postOnly": post_only}) if post_only else None
    if not post_only:
        return None
    top = _book_top(client, symbol)
    return top["ask"] if side == "buy" else top["bid"]


def _order_type(adapter: Any, post_only: bool) -> str:
    if adapter.market == "spot":
        return adapter.order_type(post_only)
    return get_gateway_config().bbo_order_type if post_only else "market"


def _emit(steps: list[dict[str, Any]], progress: Any, step: dict[str, Any]) -> None:
    steps.append(step)
    if progress:
        progress(step)


def _order_amount(adapter: Any, client: Any, symbol: str, base_quantity: float, plan: PairPlan) -> float:
    market = {"contractSize": 1.0}
    contract_size = plan.perp_contract_size if adapter.market == "perp" else 1.0
    if adapter.market == "perp":
        market["contractSize"] = float(contract_size)
    amount = adapter.base_to_order_amount(base_quantity, market)
    return amount_to_precision(client, symbol, amount)


def _default_side(plan: PairPlan, leg: str) -> str:
    if plan.intent == "close":
        return "sell" if leg == "spot" else "buy"
    return "buy" if leg == "spot" else "sell"
