from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from trading_gateway.adapters.exchanges.fees import order_fee_summary
from trading_gateway.adapters.exchanges.rules import amount_to_precision
from trading_gateway.adapters.exchanges.single_leg import adapter_for
from trading_gateway.support.redaction import redact_text
from trading_gateway.workflows.pair_trade.execution.orders import monitor_order, order_params
from trading_gateway.workflows.pair_trade.execution.reporting import add_step
from trading_gateway.workflows.pair_trade.planning.helpers import book_top
from trading_gateway.workflows.pair_trade.planning.models import PairFinalStatus, PairPlan, PairState, PairTarget
from trading_gateway.workflows.pair_trade.recovery.runtime import (
    client_for_leg,
    manual_command,
    pair_reached,
    pair_state,
    pair_target,
    remaining,
    slippage_bps,
    symbol_for_leg,
)
from trading_gateway.workflows.pair_trade.journaling.journal import PairJournal

Progress = Callable[[dict[str, object]], None]


def taker_rescue(
    spot_client: Any,
    perp_client: Any,
    plan: PairPlan,
    steps: list[dict[str, object]],
    pair_id: str,
    target: PairTarget,
    state: PairState,
    config: Any,
    timeout_sec: float,
    poll_interval_sec: float,
    progress: Progress | None,
    leg: str,
    journal: PairJournal,
) -> tuple[PairFinalStatus, PairState]:
    remaining_quantity = remaining(leg, state, target)
    client, symbol = client_for_leg(leg, spot_client, perp_client), symbol_for_leg(leg, plan)
    price = book_top(client, symbol)["ask" if leg == "spot" else "bid"]
    quote = remaining_quantity * price
    if quote > config.max_taker_rescue_quote_usdt or quote > config.max_unhedged_quote_usdt or slippage_bps(price, plan.reference_price) > config.max_slippage_bps:
        add_step(steps, {"name": "taker_rescue", "status": "blocked", "leg": leg, "remaining_quantity": remaining_quantity, "manual_command": manual_command(plan, leg, remaining_quantity)}, progress)
        return PairFinalStatus.UNHEDGED_RESCUE_FAILED, state
    cid = f"{pair_id}_rescue_{uuid.uuid4().hex[:6]}"
    rescue_side = _rescue_side(plan, leg)
    journal.order_intent({"leg": leg, "symbol": symbol, "side": rescue_side, "amount": remaining_quantity, "client_order_id": cid, "status": "rescue_intent"})
    try:
        adapter = adapter_for(plan.spot_exchange if leg == "spot" else plan.perp_exchange, "spot" if leg == "spot" else "perp")
        order = client.create_order(
            symbol,
            "market",
            rescue_side,
            amount_to_precision(client, symbol, remaining_quantity),
            None,
            order_params(adapter, client, leg, cid, post_only=False, reduce_only=plan.intent == "close" and leg == "perp"),
        )
    except Exception as exc:  # noqa: BLE001
        journal.order_update(cid, status="rescue_error", error=redact_text(exc))
        add_step(steps, {"name": "taker_rescue", "status": "error", "leg": leg, "error": redact_text(exc), "manual_command": manual_command(plan, leg, remaining_quantity)}, progress)
        return PairFinalStatus.UNHEDGED_RESCUE_FAILED, state
    journal.order_update(cid, status=order.get("status", "submitted"), order_id=order.get("id"))
    add_step(steps, {"name": "taker_rescue", "status": "submitted", "leg": leg, "order_id": order.get("id"), "amount": remaining_quantity}, progress)
    status = monitor_order(client, order, symbol, timeout_sec, poll_interval_sec, pair_id)
    add_step(steps, {"name": "taker_rescue_monitor", "status": status.get("status"), "leg": leg, "order_id": order.get("id"), "fee": order_fee_summary(plan, order, status, market=leg, amount=remaining_quantity, price=price, liquidity="taker")}, progress)
    state = pair_state(spot_client, perp_client, plan)
    final = PairFinalStatus.TARGET_REACHED if pair_reached(state, target) else PairFinalStatus.UNHEDGED_RESCUE_FAILED
    add_step(steps, {"name": "pair_verify", "status": final, **pair_target(state, target)}, progress)
    return final, state


def _rescue_side(plan: PairPlan, leg: str) -> str:
    if plan.intent == "close":
        return "sell" if leg == "spot" else "buy"
    return "buy" if leg == "spot" else "sell"
