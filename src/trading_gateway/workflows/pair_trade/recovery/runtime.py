from __future__ import annotations

from typing import Any

from trading_gateway.adapters.exchanges.positions import position_quantity
from trading_gateway.support.tolerance import quantity_tolerance_from_quote
from trading_gateway.workflows.pair_trade.planning.helpers import balance_value, hedge_mode
from trading_gateway.workflows.pair_trade.planning.models import PairPlan, PairState, PairTarget


def pair_state(spot_client: Any, perp_client: Any, plan: PairPlan) -> PairState:
    spot_balance = spot_client.fetch_balance()
    positions = perp_client.fetch_positions([plan.perp_symbol]) if hasattr(perp_client, "fetch_positions") else []
    perp_balance = perp_client.fetch_balance() if hasattr(perp_client, "fetch_balance") else {}
    return PairState(
        spot_current=balance_value(spot_balance, plan.base_asset, "total"),
        spot_quote_free=balance_value(spot_balance, plan.quote_asset, "free"),
        perp_short_current=position_quantity(positions, plan.perp_symbol, "short", hedge_mode(perp_client)),
        perp_quote_free=balance_value(perp_balance, plan.quote_asset, "free"),
    )


def pair_targets(before: PairState, quantity: float, tolerance: float, *, intent: str = "open") -> PairTarget:
    return PairTarget.from_state(before, quantity, tolerance, intent=intent)


def pair_reached(state: PairState, target: PairTarget) -> bool:
    return leg_reached("spot", state, target) and leg_reached("perp", state, target) and imbalance(state, target) <= target.tolerance


def leg_reached(leg: str, state: PairState, target: PairTarget) -> bool:
    current = state.spot_current if leg == "spot" else state.perp_short_current
    before = target.spot_before if leg == "spot" else target.perp_before
    goal = target.spot_target if leg == "spot" else target.perp_target
    if target.intent == "close":
        return current < before and current <= goal + target.tolerance
    return current > before and current >= goal - target.tolerance


def remaining(leg: str, state: PairState, target: PairTarget) -> float:
    goal = target.spot_target if leg == "spot" else target.perp_target
    current = state.spot_current if leg == "spot" else state.perp_short_current
    return max(0.0, current - goal) if target.intent == "close" else max(0.0, goal - current)


def lagging_leg(state: PairState, target: PairTarget) -> str | None:
    spot_done, perp_done = leg_reached("spot", state, target), leg_reached("perp", state, target)
    return "perp" if spot_done and not perp_done else "spot" if perp_done and not spot_done else None


def pair_target(state: PairState, target: PairTarget) -> dict[str, float]:
    return {
        "spot_current": state.spot_current,
        "spot_target": target.spot_target,
        "perp_short_current": state.perp_short_current,
        "perp_short_target": target.perp_target,
        "remaining_quantity": max(remaining("spot", state, target), remaining("perp", state, target)),
        "imbalance_quantity": imbalance(state, target),
        "tolerance_quantity": target.tolerance,
    }


def unreached_status(state: PairState, target: PairTarget) -> str:
    if imbalance(state, target) > target.tolerance and (leg_reached("spot", state, target) or leg_reached("perp", state, target)):
        return "pair_imbalanced"
    return "pair_target_not_reached"


def imbalance(state: PairState, target: PairTarget) -> float:
    if target.intent == "close":
        return abs((target.spot_before - state.spot_current) - (target.perp_before - state.perp_short_current))
    return abs((state.spot_current - target.spot_before) - (state.perp_short_current - target.perp_before))


def leg_state(leg: str, state: PairState, target: PairTarget) -> dict[str, float]:
    current = state.spot_current if leg == "spot" else state.perp_short_current
    goal = target.spot_target if leg == "spot" else target.perp_target
    return {"current_quantity": current, "target_quantity": goal, "remaining_quantity": remaining(leg, state, target)}


def funding_ok(state: PairState, plan: PairPlan) -> bool:
    return state.spot_quote_free >= plan.target_delta_quantity * float(plan.spot.best_ask or 0) and state.perp_quote_free >= plan.target_delta_quantity * plan.reference_price


def client_for_leg(leg: str, spot_client: Any, perp_client: Any) -> Any:
    return spot_client if leg == "spot" else perp_client


def symbol_for_leg(leg: str, plan: PairPlan) -> str:
    return plan.symbol if leg == "spot" else plan.perp_symbol


def tolerance(plan: PairPlan, config: Any) -> float:
    fallback = plan.quantity_step * max(0, config.target_tolerance_steps)
    return quantity_tolerance_from_quote(plan.reference_price, config.target_tolerance_quote_usdt, fallback)


def qty(plan: PairPlan) -> float:
    return plan.target_delta_quantity


def slippage_bps(price: float, reference: float) -> float:
    return abs(price - reference) / reference * 10000 if reference > 0 else 10000


def client_order_id(order: dict[str, Any]) -> str:
    raw_info = order.get("info")
    raw_params = order.get("params")
    info = raw_info if isinstance(raw_info, dict) else {}
    params = raw_params if isinstance(raw_params, dict) else {}
    return str(order.get("clientOrderId") or order.get("client_order_id") or params.get("newClientOrderId") or info.get("clientOrderId") or "")


def is_unknown_submit(exc: BaseException) -> bool:
    return any(bit in str(exc).lower() for bit in ("timeout", "network", "connection", "unknown", "read timed out"))


def is_maker_reject(exc: BaseException) -> bool:
    return any(bit in str(exc).lower() for bit in ("limit_maker", "post only", "immediately match", "maker"))


def manual_command(plan: PairPlan, leg: str, remaining_quantity: float) -> str:
    if plan.intent == "close":
        market = "spot sell" if leg == "spot" else "perp close-short"
        return f"tbot run {plan.spot_exchange if leg == 'spot' else plan.perp_exchange} {market} {plan.canonical_symbol} {remaining_quantity}"
    market = "spot buy" if leg == "spot" else "perp open-short"
    return f"tbot run {plan.spot_exchange if leg == 'spot' else plan.perp_exchange} {market} {plan.canonical_symbol} {remaining_quantity}"
