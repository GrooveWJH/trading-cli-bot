from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from trading_gateway.adapters.exchanges.fees import order_fee_summary
from trading_gateway.adapters.exchanges.positions import position_quantity, remaining_quantity, target_side
from trading_gateway.adapters.exchanges.rules import amount_to_precision
from trading_gateway.workflows.single_leg.execution.perp_context import apply_position_params, fetch_positions
from trading_gateway.workflows.single_leg.execution.perp_orders import (
    close_all_submit_step,
    order_amount,
    report_execution,
    safe_monitor_order,
    submit_error,
    submit_force_close_order,
    submit_order,
)
from trading_gateway.workflows.single_leg.recovery.close_all_state import close_all_reached, close_all_state
from trading_gateway.workflows.single_leg.recovery.runtime import close_all_target, owned_open_orders

Progress = Callable[[dict[str, Any]], None]


def run_perp_close_all(
    client: Any,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    maker_attempts: int,
    order_timeout_sec: float,
    poll_interval_sec: float,
    min_poll_interval_sec: float,
    progress: Progress | None,
    add_step: Callable[[list[dict[str, Any]], dict[str, Any], Progress | None], None],
    emit_before: Callable[[Progress | None, dict[str, Any]], None],
) -> dict[str, Any]:
    side = target_side(plan["action"])
    target = 0.0
    positions = fetch_positions(client, plan["symbol"])
    current = position_quantity(positions, plan["symbol"], side, bool(runtime.get("position_mode", {}).get("hedge")))
    state = close_all_state(client, plan, positions, current)
    apply_position_params(runtime["params"], plan, positions, side)
    add_step(steps, {"name": "position_before", "status": "ok", "side": side, **state, "positions": positions}, progress)
    if close_all_reached(state):
        add_step(steps, {"name": "close_all_verify", "status": "target_reached", "side": side, **state, "positions": positions}, progress)
        return report_execution(plan, steps, "target_reached", close_all_target(state, [], "position is flat"))
    for wave in range(max(0, maker_attempts)):
        outcome = run_close_all_wave(
            client,
            plan,
            runtime,
            steps,
            side=side,
            target=target,
            current=current,
            state=state,
            wave=wave + 1,
            wave_total=max(0, maker_attempts),
            order_timeout_sec=order_timeout_sec,
            poll_interval_sec=poll_interval_sec,
            min_poll_interval_sec=min_poll_interval_sec,
            progress=progress,
            add_step=add_step,
            emit_before=emit_before,
        )
        if outcome is not None:
            return outcome
    open_orders = owned_open_orders(client, plan["symbol"])
    if open_orders:
        add_step(steps, {"name": "close_all_verify", "status": "close_all_pending", "side": side, **state, "positions": positions}, progress)
        return report_execution(plan, steps, "close_all_pending", close_all_target(state, open_orders, "wait and re-check with snapshot / open orders"))
    return run_force_close_rescue(
        client,
        plan,
        runtime,
        steps,
        side,
        timeout_sec=order_timeout_sec,
        poll_interval_sec=poll_interval_sec,
        min_poll_interval_sec=min_poll_interval_sec,
        progress=progress,
        add_step=add_step,
    )


def run_close_all_wave(
    client: Any,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    side: str,
    target: float,
    current: float,
    state: dict[str, Any],
    wave: int,
    wave_total: int,
    order_timeout_sec: float,
    poll_interval_sec: float,
    min_poll_interval_sec: float,
    progress: Progress | None,
    add_step: Callable[[list[dict[str, Any]], dict[str, Any], Progress | None], None],
    emit_before: Callable[[Progress | None, dict[str, Any]], None],
) -> dict[str, Any] | None:
    emit_before(progress, {"name": "close_all_open_orders", "status": "start", "wave": wave, "wave_total": wave_total})
    open_orders = owned_open_orders(client, plan["symbol"])
    add_step(steps, {"name": "close_all_open_orders", "status": "ok", "wave": wave, "order_count": len(open_orders), "open_orders": open_orders}, progress)
    amount = amount_to_precision(client, plan["symbol"], order_amount(plan, remaining_quantity(plan["action"], current, target)))
    if amount > 0:
        failure = submit_and_monitor_close_all(client, plan, runtime, steps, open_orders, amount, wave, wave_total, order_timeout_sec, poll_interval_sec, min_poll_interval_sec, progress, add_step, emit_before)
        if failure is not None:
            return failure
    else:
        add_step(steps, {"name": "close_all_wave_submit", "status": "amount_unavailable", "wave": wave, "amount": amount}, progress)
    positions = fetch_positions(client, plan["symbol"])
    current = position_quantity(positions, plan["symbol"], side, bool(runtime.get("position_mode", {}).get("hedge")))
    state = close_all_state(client, plan, positions, current)
    add_step(steps, {"name": "close_all_position_poll", "status": "ok", "wave": wave, "side": side, **state, "positions": positions}, progress)
    if close_all_reached(state):
        add_step(steps, {"name": "close_all_verify", "status": "target_reached", "side": side, **state, "positions": positions}, progress)
        return report_execution(
            plan,
            steps,
            "target_reached",
            close_all_target(state, owned_open_orders(client, plan["symbol"]), "position is flat"),
        )
    return None


def submit_and_monitor_close_all(
    client: Any,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    steps: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    amount: float,
    wave: int,
    wave_total: int,
    order_timeout_sec: float,
    poll_interval_sec: float,
    min_poll_interval_sec: float,
    progress: Progress | None,
    add_step: Callable[[list[dict[str, Any]], dict[str, Any], Progress | None], None],
    emit_before: Callable[[Progress | None, dict[str, Any]], None],
) -> dict[str, Any] | None:
    order: dict[str, Any] | None = None
    emit_before(progress, {"name": "close_all_wave_submit", "status": "start", "wave": wave, "wave_total": wave_total, "amount": amount})
    try:
        order = submit_order(client, plan, amount, runtime["params"])
        add_step(steps, {"name": "close_all_wave_submit", "status": "ok", "wave": wave, "amount": amount, "price": order.get("price"), "order_id": order.get("id")}, progress)
    except Exception as exc:  # noqa: BLE001
        submit_step = close_all_submit_step(client, plan["symbol"], exc, amount)
        submit_step["wave"] = wave
        add_step(steps, {"name": "close_all_wave_submit", **submit_step}, progress)
        if submit_step["status"] == "submit_error":
            state = {"remaining_quantity": amount, "remaining_quote_usdt": 0.0}
            return report_execution(plan, steps, "submit_error", close_all_target(state, open_orders, "rerun close-short BTC/USDT --confirm ..."))
        return None
    emit_before(progress, {"name": "close_all_order_monitor", "status": "start", "wave": wave, "wave_total": wave_total, "order_id": order.get("id")})
    status = safe_monitor_order(client, order, plan["symbol"], order_timeout_sec, poll_interval_sec, min_poll_interval_sec)
    fee = order_fee_summary(plan, order, status, amount=amount, price=order.get("price"), liquidity="maker")
    add_step(steps, {"name": "close_all_order_monitor", "status": status.get("status"), "wave": wave, "order_id": order.get("id"), "fee": fee}, progress)
    return None


def run_force_close_rescue(
    client: Any,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    steps: list[dict[str, Any]],
    side: str,
    *,
    timeout_sec: float,
    poll_interval_sec: float,
    min_poll_interval_sec: float,
    progress: Progress | None,
    add_step: Callable[[list[dict[str, Any]], dict[str, Any], Progress | None], None],
) -> dict[str, Any]:
    max_attempts = 3
    last_positions: list[dict[str, Any]] = []
    last_error: str | None = None
    for attempt in range(max_attempts):
        open_orders = owned_open_orders(client, plan["symbol"])
        if open_orders:
            return report_execution(plan, steps, "close_all_pending", close_all_target({"remaining_quantity": 0.0, "remaining_quote_usdt": 0.0}, open_orders, "wait for stale close orders to cancel before force close"))
        positions = fetch_positions(client, plan["symbol"])
        last_positions = positions
        current = position_quantity(positions, plan["symbol"], side, bool(runtime.get("position_mode", {}).get("hedge")))
        state = close_all_state(client, plan, positions, current)
        add_step(steps, {"name": "force_close_position_before", "status": "ok", "attempt": attempt + 1, "side": side, **state, "positions": positions}, progress)
        if close_all_reached(state):
            add_step(steps, {"name": "force_close_verify", "status": "target_reached", "side": side, **state, "positions": positions}, progress)
            return report_execution(plan, steps, "target_reached", close_all_target(state, [], "position is flat"))
        amount = amount_to_precision(client, plan["symbol"], order_amount(plan, current))
        if amount <= 0:
            last_error = "force close amount rounded to zero"
            add_step(steps, {"name": "force_close_submit", "status": "amount_unavailable", "attempt": attempt + 1, "amount": amount}, progress)
            break
        try:
            order = submit_force_close_order(client, plan, amount, runtime["params"])
            add_step(steps, {"name": "force_close_submit", "status": "ok", "attempt": attempt + 1, "amount": amount, "order_id": order.get("id")}, progress)
        except Exception as exc:  # noqa: BLE001
            last_error = submit_error(exc)
            add_step(steps, {"name": "force_close_submit", "status": "error", "attempt": attempt + 1, "amount": amount, "error": last_error}, progress)
            continue
        status = safe_monitor_order(client, order, plan["symbol"], timeout_sec, poll_interval_sec, min_poll_interval_sec)
        fee = order_fee_summary(plan, order, status, amount=amount, price=order.get("price"), liquidity="taker")
        add_step(steps, {"name": "force_close_order_monitor", "status": status.get("status"), "attempt": attempt + 1, "order_id": order.get("id"), "fee": fee}, progress)
        time.sleep(max(0.0, poll_interval_sec))
    positions = fetch_positions(client, plan["symbol"])
    if positions:
        last_positions = positions
    current = position_quantity(last_positions, plan["symbol"], side, bool(runtime.get("position_mode", {}).get("hedge")))
    state = close_all_state(client, plan, last_positions, current)
    if close_all_reached(state):
        add_step(steps, {"name": "force_close_verify", "status": "target_reached", "side": side, **state, "positions": last_positions}, progress)
        return report_execution(plan, steps, "target_reached", close_all_target(state, [], "position is flat"))
    if last_error:
        state = {**state, "last_force_close_error": last_error}
    add_step(steps, {"name": "force_close_verify", "status": "force_close_failed", "side": side, **state, "positions": last_positions}, progress)
    return report_execution(plan, steps, "force_close_failed", close_all_target(state, owned_open_orders(client, plan["symbol"]), "manual intervention required: force close failed"))
