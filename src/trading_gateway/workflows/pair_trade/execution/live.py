from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_gateway.adapters.exchanges.fees import order_fee_summary
from trading_gateway.adapters.exchanges.leverage import ensure_perp_leverage
from trading_gateway.app.config import get_gateway_config
from trading_gateway.workflows.pair_trade.execution.orders import cancel_order, monitor_order, submit_leg
from trading_gateway.workflows.pair_trade.execution.overfill import correct_overfill
from trading_gateway.workflows.pair_trade.execution.reporting import add_step, finish_execution, report_execution
from trading_gateway.workflows.pair_trade.execution.rescue import taker_rescue
from trading_gateway.workflows.pair_trade.journaling.journal import PairJournal, load_pair_journal, validate_pair_journal
from trading_gateway.workflows.pair_trade.planning.models import PairFinalStatus, PairPlan, PairState, PairTarget
from trading_gateway.workflows.pair_trade.recovery.runtime import (
    client_for_leg,
    client_order_id,
    funding_ok,
    lagging_leg,
    leg_reached,
    leg_state,
    pair_reached,
    pair_state,
    pair_target,
    pair_targets,
    qty,
    symbol_for_leg,
    tolerance,
    unreached_status,
)
from trading_gateway.workflows.pair_trade.recovery.safety import capacity_limited_amount, external_open_orders, redacted_orders

Progress = Callable[[dict[str, Any]], None]
TERMINAL_ERROR = {PairFinalStatus.SUBMIT_ERROR, PairFinalStatus.ORDER_STATE_UNKNOWN, PairFinalStatus.BLOCKED}


def run_live_execution(
    spot_client: Any,
    perp_client: Any,
    plan: dict[str, Any],
    *,
    confirm: str,
    timeout_sec: float | None = None,
    normal_max_requotes: int | None = None,
    recovery_max_requotes: int | None = None,
    poll_interval_sec: float | None = None,
    journal_dir: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    typed_plan = PairPlan.from_mapping(plan)
    root_config = get_gateway_config()
    config = root_config.pair_execution
    timeout = root_config.spot_execution.order_timeout_sec if timeout_sec is None else timeout_sec
    normal_requotes = config.normal_max_requotes if normal_max_requotes is None else normal_max_requotes
    recovery_requotes = config.unhedged_recovery_max_requotes if recovery_max_requotes is None else recovery_max_requotes
    poll = config.poll_interval_sec if poll_interval_sec is None else poll_interval_sec
    steps: list[dict[str, Any]] = []
    add_step(steps, {"name": "pair_plan", "status": "ok", "can_execute": typed_plan.can_execute}, progress)
    if not typed_plan.can_execute:
        return report_execution(typed_plan, steps, PairFinalStatus.BLOCKED)
    if root_config.safety.require_live_confirm and str(confirm or "").strip() != typed_plan.confirm_phrase:
        add_step(steps, {"name": "live_confirm", "status": "blocked", "expected_confirm_phrase": typed_plan.confirm_phrase}, progress)
        return report_execution(typed_plan, steps, PairFinalStatus.BLOCKED)
    pair_id = journal_pair_id()
    journal = PairJournal(pair_id, journal_dir)
    before = pair_state(spot_client, perp_client, typed_plan)
    target = pair_targets(before, qty(typed_plan), tolerance(typed_plan, config), intent=typed_plan.intent)
    journal.start(typed_plan, before, target)
    add_step(steps, {"name": "spot_balance_before", "status": "ok", **leg_state("spot", before, target)}, progress)
    add_step(steps, {"name": "perp_position_before", "status": "ok", **leg_state("perp", before, target)}, progress)
    external = external_open_orders(spot_client, perp_client, typed_plan, pair_id)
    add_step(steps, {"name": "external_open_order_audit", "status": "blocked" if external and config.external_open_order_policy == "block" else "ok", "open_orders": redacted_orders(external)}, progress)
    if external and config.external_open_order_policy == "block":
        return finish_execution(journal, typed_plan, steps, PairFinalStatus.BLOCKED, pair_target(before, target), pair_id)
    if typed_plan.intent != "close" and not funding_ok(before, typed_plan):
        add_step(steps, {"name": "funding_check", "status": "blocked"}, progress)
        return finish_execution(journal, typed_plan, steps, PairFinalStatus.BLOCKED, pair_target(before, target), pair_id)
    leverage = ensure_perp_leverage(perp_client, typed_plan.perp_symbol, root_config.perp_execution.target_leverage)
    add_step(steps, {"name": "perp_leverage", **leverage}, progress)
    if leverage["status"] != "ok":
        return finish_execution(journal, typed_plan, steps, PairFinalStatus.BLOCKED, pair_target(before, target), pair_id)
    status, state = maker_loop(spot_client, perp_client, typed_plan, steps, pair_id, target, normal_requotes, timeout, poll, progress, journal)
    if status == PairFinalStatus.TARGET_REACHED or status in TERMINAL_ERROR:
        return finish_execution(journal, typed_plan, steps, status, pair_target(state, target), pair_id)
    lagging = lagging_leg(state, target)
    if lagging:
        add_step(steps, {"name": "unhedged_recovery", "status": "pair_unhedged_recovering", "leg": lagging}, progress)
        status, state = maker_loop(spot_client, perp_client, typed_plan, steps, pair_id, target, recovery_requotes, timeout, poll, progress, journal, only_leg=lagging)
        if status == PairFinalStatus.TARGET_REACHED or status in TERMINAL_ERROR:
            return finish_execution(journal, typed_plan, steps, status, pair_target(state, target), pair_id)
        if config.allow_taker_rescue:
            status, state = taker_rescue(spot_client, perp_client, typed_plan, steps, pair_id, target, state, config, timeout, poll, progress, lagging, journal)
            return finish_execution(journal, typed_plan, steps, status, pair_target(state, target), pair_id)
        status = PairFinalStatus(unreached_status(state, target))
        return finish_execution(journal, typed_plan, steps, status, pair_target(state, target), pair_id)
    status = PairFinalStatus(unreached_status(state, target))
    if status == PairFinalStatus.IMBALANCED:
        status, state = correct_overfill(spot_client, perp_client, typed_plan, steps, pair_id, target, state, config, timeout, poll, progress, journal)
    return finish_execution(journal, typed_plan, steps, PairFinalStatus(status), pair_target(state, target), pair_id)
def resume_live_execution(
    spot_client: Any,
    perp_client: Any,
    pair_id: str,
    *,
    confirm: str,
    timeout_sec: float | None = None,
    normal_max_requotes: int | None = None,
    journal_dir: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    journal_payload = load_pair_journal(pair_id, journal_dir)
    validate_pair_journal(journal_payload)
    plan = PairPlan.from_mapping(journal_payload["plan"])
    target = PairTarget.from_mapping(journal_payload["target"])
    root_config = get_gateway_config()
    config = root_config.pair_execution
    steps: list[dict[str, Any]] = []
    state = pair_state(spot_client, perp_client, plan)
    add_step(steps, {"name": "pair_resume", "status": "ok", **pair_target(state, target)}, progress)
    if pair_reached(state, target):
        return report_execution(plan, steps, PairFinalStatus.TARGET_REACHED, pair_target(state, target), pair_id)
    if root_config.safety.require_live_confirm and str(confirm or "").strip() != plan.confirm_phrase:
        add_step(steps, {"name": "live_confirm", "status": "blocked", "expected_confirm_phrase": plan.confirm_phrase}, progress)
        return report_execution(plan, steps, PairFinalStatus.BLOCKED, pair_target(state, target), pair_id)
    journal = PairJournal(pair_id, journal_dir)
    journal.event("pair_resumed", "ok", target=pair_target(state, target))
    external = external_open_orders(spot_client, perp_client, plan, pair_id)
    add_step(steps, {"name": "external_open_order_audit", "status": "blocked" if external and config.external_open_order_policy == "block" else "ok", "open_orders": redacted_orders(external)}, progress)
    if external and config.external_open_order_policy == "block":
        return finish_execution(journal, plan, steps, PairFinalStatus.BLOCKED, pair_target(state, target), pair_id)
    leverage = ensure_perp_leverage(perp_client, plan.perp_symbol, root_config.perp_execution.target_leverage)
    add_step(steps, {"name": "perp_leverage", **leverage}, progress)
    if leverage["status"] != "ok":
        return finish_execution(journal, plan, steps, PairFinalStatus.BLOCKED, pair_target(state, target), pair_id)
    timeout = root_config.spot_execution.order_timeout_sec if timeout_sec is None else timeout_sec
    max_requotes = config.normal_max_requotes if normal_max_requotes is None else normal_max_requotes
    status, state = maker_loop(spot_client, perp_client, plan, steps, pair_id, target, max_requotes, timeout, config.poll_interval_sec, progress, journal)
    return finish_execution(journal, plan, steps, status, pair_target(state, target), pair_id)
def maker_loop(
    spot_client: Any,
    perp_client: Any,
    plan: PairPlan,
    steps: list[dict[str, Any]],
    pair_id: str,
    target: PairTarget,
    max_requotes: int,
    timeout_sec: float,
    poll_interval_sec: float,
    progress: Progress | None,
    journal: PairJournal,
    only_leg: str | None = None,
) -> tuple[PairFinalStatus, PairState]:
    state = pair_state(spot_client, perp_client, plan)
    for attempt in range(max_requotes + 1):
        submit_status, orders = submit_needed(spot_client, perp_client, plan, pair_id, target, state, attempt + 1, progress, steps, journal, only_leg)
        if submit_status in TERMINAL_ERROR:
            return PairFinalStatus(submit_status), state
        for leg, order in orders:
            client, symbol = client_for_leg(leg, spot_client, perp_client), symbol_for_leg(leg, plan)
            status = monitor_order(client, order, symbol, timeout_sec, poll_interval_sec, pair_id)
            fee = order_fee_summary(plan, order, status, market=leg, amount=order.get("amount"), price=order.get("price"), liquidity="maker")
            add_step(steps, {"name": "monitor", "status": status.get("status"), "leg": leg, "order_id": order.get("id"), "fee": fee}, progress)
            journal.order_update(client_order_id(order), order_id=order.get("id"), status=status.get("status"))
            if status.get("status") == "unknown":
                return PairFinalStatus.ORDER_STATE_UNKNOWN, state
            if status.get("status") not in {"closed", "canceled", "rejected", "expired"} and not cancel_order(client, symbol, order, steps, progress, leg, journal, pair_id):
                return PairFinalStatus.ORDER_STATE_UNKNOWN, state
        state = pair_state(spot_client, perp_client, plan)
        add_step(steps, {"name": "verify_after_cancel", "status": "ok", **pair_target(state, target)}, progress)
        if pair_reached(state, target):
            add_step(steps, {"name": "pair_verify", "status": PairFinalStatus.TARGET_REACHED, **pair_target(state, target)}, progress)
            return PairFinalStatus.TARGET_REACHED, state
        if attempt < max_requotes:
            add_step(steps, {"name": "requote", "status": "pending", "attempt": attempt + 2, **pair_target(state, target)}, progress)
    return PairFinalStatus(unreached_status(state, target)), state


def submit_needed(
    spot_client: Any,
    perp_client: Any,
    plan: PairPlan,
    pair_id: str,
    target: PairTarget,
    state: PairState,
    attempt: int,
    progress: Progress | None,
    steps: list[dict[str, Any]],
    journal: PairJournal,
    only_leg: str | None,
) -> tuple[PairFinalStatus | str, list[tuple[str, dict[str, Any]]]]:
    orders: list[tuple[str, dict[str, Any]]] = []
    root_config = get_gateway_config()
    for leg in ("spot", "perp"):
        if (only_leg and leg != only_leg) or leg_reached(leg, state, target):
            continue
        client = client_for_leg(leg, spot_client, perp_client)
        amount, capacity = capacity_limited_amount(client, plan, leg, state, target, root_config.pair_execution, root_config.perp_execution.target_leverage)
        if capacity["status"] != "ok":
            add_step(steps, {"name": f"{leg}_capacity_check", **capacity}, progress)
        if capacity["status"] == "blocked":
            return PairFinalStatus.BLOCKED, orders
        status, order = submit_leg(
            client,
            plan,
            leg,
            amount,
            pair_id,
            attempt,
            journal,
            side=_submit_side(plan, leg),
            reduce_only=plan.intent == "close" and leg == "perp",
        )
        step: dict[str, Any] = {"name": f"submit_{leg}", "status": status, "attempt": attempt, "amount": amount}
        if order:
            step["order_id"] = order.get("id")
            orders.append((leg, order))
        add_step(steps, step, progress)
        if status in TERMINAL_ERROR:
            return status, orders
    return "ok", orders


def _submit_side(plan: PairPlan, leg: str) -> str | None:
    if plan.intent == "close":
        return "sell" if leg == "spot" else "buy"
    return None

def journal_pair_id() -> str:
    import uuid

    return f"aspair_{uuid.uuid4().hex[:16]}"
