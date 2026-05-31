from __future__ import annotations

from typing import Any

from rich.table import Table

from trading_gateway.app.config import get_gateway_config


def base_table() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    return table


def text(value: Any) -> str:
    return "-" if value is None else str(value)


def fmt_float(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.8g}"
    except (TypeError, ValueError):
        return str(value)


def first_step(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((row for row in payload.get("steps") or [] if row.get("name") == name), None)


def first_step_value(payload: dict[str, Any], name: str, key: str) -> str:
    return text((first_step(payload, name) or {}).get(key))


def progress_prefix(step: dict[str, Any]) -> str:
    if "attempt" in step:
        total = step.get("attempt_total")
        if total is not None:
            return f"[{step.get('attempt')}/{total}] "
    if "wave" in step:
        total = step.get("wave_total")
        if total is not None:
            return f"[{step.get('wave')}/{total}] "
    return ""


def is_effectively_zero(value: Any, tolerance: Any) -> bool:
    try:
        return abs(float(value or 0)) <= float(tolerance or 0)
    except (TypeError, ValueError):
        return False


def effectively_done(target: dict[str, Any]) -> bool:
    remaining_quote = target.get("remaining_quote_usdt")
    if remaining_quote is not None:
        try:
            return float(remaining_quote) <= get_gateway_config().perp_execution.target_tolerance_quote_usdt
        except (TypeError, ValueError):
            return False
    return is_effectively_zero(target.get("remaining_quantity"), target.get("tolerance_quantity"))


def fee_text(payload: dict[str, Any]) -> str:
    fees = payload.get("fees") or {}
    items = fees.get("items") or []
    if not items:
        if payload.get("final_status") == "target_reached" and not first_step(payload, "submit") and not first_step(payload, "close_all_wave_submit"):
            return "none (no order submitted in this invocation)"
        return "-"
    parts = []
    for item in items[:3]:
        prefix = "estimated " if item.get("source") == "estimated" else "actual "
        rate = f"@ {fmt_float(item.get('rate_bps'))} bps {item.get('liquidity', '')}".strip()
        if item.get("cost") is None:
            parts.append(f"{prefix}rate only {rate}")
        else:
            parts.append(f"{prefix}{fmt_float(item.get('cost'))} {item.get('currency', 'USDT')} {rate}")
    if len(items) > 3:
        parts.append(f"+{len(items) - 3} more")
    return " | ".join(parts)
