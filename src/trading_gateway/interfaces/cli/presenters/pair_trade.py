from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel

from trading_gateway.app.config import get_gateway_config

from .common import base_table, fee_text, text
from .single_leg import leverage_text


def print_pair_plan_brief(plan: dict[str, Any], query_ms: int) -> None:
    is_close = plan.get("intent") == "close" or plan.get("mode") == "pair_close_plan"
    status = "CAN EXECUTE" if plan.get("can_execute") else "BLOCKED"
    style = "bold green" if plan.get("can_execute") else "bold red"
    plan_name = "Pair Close Plan" if is_close else "Pair Plan"
    title = f"{plan_name}: {status}  query_ms={query_ms}  {plan.get('spot_exchange')} spot + {plan.get('perp_exchange')} perp {plan.get('symbol')}"
    table = base_table()
    table.add_row("intent", "close" if is_close else "open")
    if not is_close:
        table.add_row("requested_quote_usdt", text(plan.get("requested_quote_usdt")))
    table.add_row("target_delta_quantity", text(plan.get("target_delta_quantity")))
    table.add_row("reference_price", text(plan.get("reference_price")))
    table.add_row("perp_target_leverage", text(plan.get("perp_target_leverage")))
    table.add_row("fee_rate", pair_fee_rate_text())
    data_sources = plan.get("planning_data_sources") or {}
    table.add_row("account_state", planning_source_text(data_sources))
    minimums = plan.get("minimums") or {}
    if minimums:
        table.add_row("minimum", pair_minimum_text(plan))
    table.add_row("spot_target", pair_side_text(plan.get("spot") or {}, "target_quantity"))
    table.add_row("perp_target", pair_side_text(plan.get("perp") or {}, "target_short_quantity"))
    if plan.get("warnings"):
        table.add_row("reason", "\n".join(f"{row.get('code', 'warning')}: {row.get('message', row)}" for row in plan.get("warnings") or []))
    else:
        table.add_row("preview", pair_preview_text(plan))
        next_command = (
            f"pair-close-run {plan.get('spot_exchange')} {plan.get('perp_exchange')} {plan.get('symbol')} --confirm \"{plan.get('confirm_phrase')}\""
            if is_close
            else f"pair-run {plan.get('spot_exchange')} {plan.get('perp_exchange')} {plan.get('symbol')} {plan.get('requested_quote_usdt')} --confirm \"{plan.get('confirm_phrase')}\""
        )
        table.add_row("next", next_command)
    Console(stderr=True, width=120).print(Panel(table, title=title, style=style))


def print_pair_run_brief(payload: dict[str, Any]) -> None:
    plan = payload.get("plan") or {}
    is_close = plan.get("intent") == "close" or plan.get("mode") == "pair_close_plan"
    status = str(payload.get("final_status") or "unknown")
    style = "bold green" if status == "pair_target_reached" else "bold red"
    title = f"{'Pair Close Run' if is_close else 'Pair Run'}: {status.upper()}  query_ms={payload.get('query_ms')}  {plan.get('symbol')}"
    target = payload.get("target") or {}
    table = base_table()
    table.add_row("target_delta_quantity", text(plan.get("target_delta_quantity")))
    table.add_row("perp_target_leverage", leverage_text(payload))
    table.add_row("spot", f"current={text(target.get('spot_current'))} target={text(target.get('spot_target'))}")
    table.add_row("perp_short", f"current={text(target.get('perp_short_current'))} target={text(target.get('perp_short_target'))}")
    table.add_row("remaining", text(target.get("remaining_quantity")))
    table.add_row("imbalance", text(target.get("imbalance_quantity")))
    table.add_row("fees", fee_text(payload))
    table.add_row("timeline", " -> ".join(f"{row.get('name')}:{row.get('status')}" for row in payload.get("steps") or []))
    Console(stderr=True, width=120).print(Panel(table, title=title, style=style))


def print_pair_status_brief(payload: dict[str, Any]) -> None:
    plan = payload.get("plan") or {}
    is_close = plan.get("intent") == "close" or plan.get("mode") == "pair_close_plan"
    status = str(payload.get("final_status") or "unknown")
    style = "bold green" if status == "pair_target_reached" else "bold yellow"
    title = f"{'Pair Close Status' if is_close else 'Pair Status'}: {status.upper()}  pair_id={payload.get('pair_id')}"
    target = payload.get("target") or {}
    table = base_table()
    table.add_row("spot", f"current={text(target.get('spot_current'))} target={text(target.get('spot_target'))}")
    table.add_row("perp_short", f"current={text(target.get('perp_short_current'))} target={text(target.get('perp_short_target'))}")
    table.add_row("remaining", text(target.get("remaining_quantity")))
    table.add_row("imbalance", text(target.get("imbalance_quantity")))
    table.add_row("open_orders", text(len(payload.get("open_orders") or [])))
    table.add_row("suggested", " | ".join(payload.get("suggested_actions") or []))
    Console(stderr=True, width=120).print(Panel(table, title=title, style=style))


def pair_side_text(row: dict[str, Any], key: str) -> str:
    current = row.get("current_quantity") if "current_quantity" in row else row.get("current_short_quantity")
    return f"current={text(current)} target={text(row.get(key))}"


def pair_preview_text(plan: dict[str, Any]) -> str:
    preview = plan.get("execution_preview") or {}
    if plan.get("intent") == "close" or plan.get("mode") == "pair_close_plan":
        return (
            f"spot sell {text(preview.get('spot_current_quantity'))} -> {text(preview.get('spot_target_quantity'))} | "
            f"perp buy-to-close {text(preview.get('perp_short_current_quantity'))} -> {text(preview.get('perp_short_target_quantity'))}"
        )
    return (
        f"spot {text(preview.get('spot_current_quantity'))} -> {text(preview.get('spot_target_quantity'))} | "
        f"perp short {text(preview.get('perp_short_current_quantity'))} -> {text(preview.get('perp_short_target_quantity'))}"
    )


def pair_fee_rate_text() -> str:
    config = get_gateway_config()
    return f"spot {config.fee_bps('spot', 'maker', 'binance'):.8g} bps maker | perp {config.fee_bps('perp', 'maker', 'binance'):.8g} bps maker"


def planning_source_text(payload: dict[str, Any]) -> str:
    source = str(payload.get("account_state_source") or "-")
    age = payload.get("account_state_age_sec")
    fallback = payload.get("fallback_reason")
    text_value = source
    if age is not None:
        text_value = f"{text_value} age={age:.2f}s"
    if fallback:
        text_value = f"{text_value} fallback={fallback}"
    return text_value


def pair_minimum_text(plan: dict[str, Any]) -> str:
    minimums = plan.get("minimums") or {}
    spot = minimums.get("spot") or {}
    perp = minimums.get("perp") or {}
    source = minimums.get("effective_source") or "-"
    return (
        f"effective {source} {text(plan.get('min_executable_quote_usdt'))} USDT | "
        f"spot min qty {text(spot.get('min_quantity'))} quote {text(spot.get('min_quote_usdt'))} | "
        f"perp min qty {text(perp.get('min_quantity'))} quote {text(perp.get('min_quote_usdt'))}"
    )
