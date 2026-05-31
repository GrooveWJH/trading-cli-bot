from __future__ import annotations

from typing import Any

from trading_gateway.adapters.exchanges.fees import order_fee_summary
from trading_gateway.workflows.pair_trade.execution.orders import cancel_order, monitor_order, submit_leg
from trading_gateway.workflows.pair_trade.planning.models import PairFinalStatus, PairPlan, PairState, PairTarget
from trading_gateway.workflows.pair_trade.recovery.runtime import client_for_leg, pair_reached, pair_state, pair_target, symbol_for_leg
from trading_gateway.workflows.pair_trade.recovery.safety import overfill_delta, overfill_quote

Progress = Any


def correct_overfill(
    spot_client: Any,
    perp_client: Any,
    plan: PairPlan,
    steps: list[dict[str, Any]],
    pair_id: str,
    target: PairTarget,
    state: PairState,
    config: Any,
    timeout_sec: float,
    poll_interval_sec: float,
    progress: Progress,
    journal: Any,
) -> tuple[PairFinalStatus, PairState]:
    overfill = overfill_delta(state, target)
    if not overfill:
        return PairFinalStatus.IMBALANCED, state
    leg, amount = str(overfill["lagging_leg"]), float(overfill["excess_quantity"])
    quote = overfill_quote(client_for_leg(leg, spot_client, perp_client), plan, leg, amount)
    _add(steps, {"name": "overfill_detected", "status": "pending", **overfill, "quote_usdt": quote}, progress)
    if config.overfill_policy == "match_lagging" and quote <= config.max_overfill_quote_usdt:
        return _trade(spot_client, perp_client, plan, steps, pair_id, target, timeout_sec, poll_interval_sec, progress, journal, leg, amount, "overfill_match_lagging")
    _add(steps, {"name": "overfill_match_lagging", "status": "blocked", "leg": leg, "amount": amount}, progress)
    if not config.allow_reduce_overfilled_leg:
        return PairFinalStatus.IMBALANCED, state
    reduce_leg = str(overfill["overfilled_leg"])
    side = "sell" if reduce_leg == "spot" else "buy"
    return _trade(spot_client, perp_client, plan, steps, pair_id, target, timeout_sec, poll_interval_sec, progress, journal, reduce_leg, amount, "overfill_reduce", side=side, reduce_only=reduce_leg == "perp")


def _trade(
    spot_client: Any,
    perp_client: Any,
    plan: PairPlan,
    steps: list[dict[str, Any]],
    pair_id: str,
    target: PairTarget,
    timeout_sec: float,
    poll_interval_sec: float,
    progress: Progress,
    journal: Any,
    leg: str,
    amount: float,
    name: str,
    *,
    side: str | None = None,
    reduce_only: bool = False,
) -> tuple[PairFinalStatus, PairState]:
    client = client_for_leg(leg, spot_client, perp_client)
    status, order = submit_leg(client, plan, leg, amount, pair_id, 1, journal, side=side, reduce_only=reduce_only)
    _add(steps, {"name": name, "status": status, "leg": leg, "amount": amount, "order_id": order.get("id") if order else None}, progress)
    terminal = {PairFinalStatus.SUBMIT_ERROR, PairFinalStatus.ORDER_STATE_UNKNOWN}
    if status in terminal or not order:
        return PairFinalStatus(status) if status in terminal else PairFinalStatus.IMBALANCED, pair_state(spot_client, perp_client, plan)
    result = monitor_order(client, order, symbol_for_leg(leg, plan), timeout_sec, poll_interval_sec, pair_id)
    fee = order_fee_summary(plan, order, result, market=leg, amount=amount, liquidity="maker")
    _add(steps, {"name": "monitor", "status": result.get("status"), "leg": leg, "order_id": order.get("id"), "fee": fee}, progress)
    if result.get("status") not in {"closed", "canceled", "rejected", "expired"}:
        cancel_order(client, symbol_for_leg(leg, plan), order, steps, progress, leg, journal, pair_id)
    state = pair_state(spot_client, perp_client, plan)
    final = PairFinalStatus.TARGET_REACHED if pair_reached(state, target) else PairFinalStatus.IMBALANCED
    _add(steps, {"name": "pair_verify", "status": final, **pair_target(state, target)}, progress)
    return final, state


def _add(steps: list[dict[str, Any]], step: dict[str, Any], progress: Progress) -> None:
    if isinstance(step.get("status"), PairFinalStatus):
        step = {**step, "status": str(step["status"])}
    steps.append(step)
    if progress:
        progress(step)
