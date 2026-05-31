from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def print_account_snapshot_rich(payload: dict[str, Any]) -> None:
    console = Console(width=180)
    title = (
        "Account Snapshot  "
        f"query_ms={payload.get('query_ms', '-')} "
        f"assets={payload.get('totals', {}).get('assets', '-')} "
        f"positions={payload.get('totals', {}).get('open_positions', '-')}"
    )
    console.print(Panel.fit(title, style="bold cyan"))
    _print_assets(console, payload)
    _print_positions(console, payload)
    _print_warnings(console, payload)


def _print_assets(console: Console, payload: dict[str, Any]) -> None:
    table = Table(title="Spot / Margin Assets", header_style="bold")
    for column in ("Exchange", "Account", "Asset", "Total", "Free", "Locked", "ValueUSDT", "Status"):
        table.add_column(column, no_wrap=True)
    for exchange in payload.get("exchanges", []):
        _asset_rows(table, exchange["exchange"], "spot", (exchange.get("spot") or {}).get("assets") or [])
        _asset_rows(table, exchange["exchange"], "perp", (exchange.get("perp") or {}).get("assets") or [])
    console.print(table)


def _asset_rows(table: Table, exchange: str, account: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        table.add_row(exchange, account, "-", "-", "-", "-", "-", "empty", style="dim")
        return
    for row in rows:
        table.add_row(
            exchange,
            account,
            row.get("asset", "-"),
            row.get("total", "-"),
            row.get("free", "-"),
            row.get("locked", "-"),
            row.get("usdt_value") or "-",
            row.get("status", "ok"),
            style="green" if row.get("total") not in ("", "0", None) else "dim",
        )


def _print_positions(console: Console, payload: dict[str, Any]) -> None:
    table = Table(title="Perp Positions", header_style="bold")
    columns = ("Exchange", "Symbol", "Side", "BaseQty", "Contracts", "ValueUSDT", "Entry", "Mark", "UPL", "Lev", "Margin", "Liq", "Action")
    for column in columns:
        table.add_column(column, no_wrap=True)
    for exchange in payload.get("exchanges", []):
        rows = (exchange.get("perp") or {}).get("positions") or []
        if not rows:
            table.add_row(exchange["exchange"], "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", style="dim")
            continue
        for row in rows:
            _position_row(table, exchange["exchange"], row)
    console.print(table)


def _position_row(table: Table, exchange: str, row: dict[str, Any]) -> None:
    side = row.get("side", "flat")
    style = "red" if side == "short" else "green" if side == "long" else "dim"
    canonical = _canonical_symbol(row)
    action = _close_command(exchange, side, canonical)
    table.add_row(
        exchange,
        row.get("symbol", "-"),
        side,
        _base_quantity(row),
        row.get("contracts", "-"),
        _position_usdt_value(row),
        row.get("entry_price", "-"),
        row.get("mark_price", "-"),
        row.get("unrealized_pnl", "-"),
        row.get("leverage", "-"),
        row.get("margin_mode", "-"),
        row.get("liq_price", "-"),
        action,
        style=style,
    )


def _canonical_symbol(row: dict[str, Any]) -> str:
    base = str(row.get("base") or "").upper()
    quote = str(row.get("quote") or "USDT").upper()
    if base and quote:
        return f"{base}/{quote}"
    return str(row.get("symbol") or "-")


def _base_quantity(row: dict[str, Any]) -> str:
    notional_qty = _base_quantity_from_notional(row)
    if notional_qty != "-":
        return notional_qty
    try:
        return f"{abs(float(row.get('contracts') or 0) * float(row.get('contract_size') or 1)):.12g}"
    except (TypeError, ValueError):
        return row.get("size", "-")


def _base_quantity_from_notional(row: dict[str, Any]) -> str:
    try:
        notional = abs(float(row.get("notional_usdt") or 0))
        mark = abs(float(row.get("mark_price") or 0))
    except (TypeError, ValueError):
        return "-"
    if notional <= 0 or mark <= 0:
        return "-"
    return f"{notional / mark:.12g}"


def _position_usdt_value(row: dict[str, Any]) -> str:
    try:
        notional = abs(float(row.get("notional_usdt") or 0))
    except (TypeError, ValueError):
        notional = 0
    if notional > 0:
        return f"{notional:.12g}"

    try:
        base_qty = abs(float(_base_quantity(row)))
        mark = abs(float(row.get("mark_price") or 0))
    except (TypeError, ValueError):
        return "-"
    if base_qty <= 0 or mark <= 0:
        return "-"
    return f"{base_qty * mark:.12g}"


def _close_command(exchange: str, side: str, canonical: str) -> str:
    if side not in {"long", "short"} or canonical == "-":
        return "-"
    return f"run {exchange} perp close-{side} {canonical} --bbo"


def _print_warnings(console: Console, payload: dict[str, Any]) -> None:
    warnings = payload.get("warnings") or []
    if warnings:
        console.print(Panel("\n".join(str(row) for row in warnings), title="Warnings", style="yellow"))
