from __future__ import annotations

from typing import Annotated

import typer

from trading_gateway.application.risk.okx_algo import (
    OkxBracketIntent,
    build_okx_bracket_plan,
    cancel_okx_algo_orders,
    fetch_okx_algo_orders,
    okx_bracket_confirm_phrase,
    place_okx_bracket_orders,
)
from trading_gateway.infrastructure.exchange.factory import build_ccxt_client, close_client
from trading_gateway.support.formatting import print_json
from trading_gateway.support.redaction import redact_text

JsonOpt = Annotated[bool, typer.Option("--json", help="print machine-readable JSON")]


def register_risk_commands(app: typer.Typer) -> None:
    app.command("plan", help="Build an OKX TP/SL trigger-order plan; never places orders.")(risk_plan)
    app.command("bracket", help="Place OKX reduce-only TP/SL trigger orders after exact confirmation.")(risk_bracket)
    app.command("orders", help="List pending OKX conditional algo orders.")(risk_orders)
    app.command("cancel", help="Cancel pending OKX algo orders after exact confirmation.")(risk_cancel)


def risk_plan(
    exchange: Annotated[str, typer.Argument(help="currently only okx")],
    symbol: Annotated[str, typer.Argument(help="OKX instrument id, e.g. BTC-USDT-SWAP")],
    side: Annotated[str, typer.Argument(help="current position side: long/short")],
    size: Annotated[float, typer.Argument(help="position size to close")],
    take_profit: Annotated[float | None, typer.Option("--take-profit", help="take-profit trigger price")] = None,
    stop_loss: Annotated[float | None, typer.Option("--stop-loss", help="stop-loss trigger price")] = None,
    margin_mode: Annotated[str, typer.Option("--margin-mode", help="cross/isolated")] = "cross",
    trigger_px_type: Annotated[str, typer.Option("--trigger-px-type", help="last/index/mark")] = "last",
    order_px: Annotated[str, typer.Option("--order-px", help="-1 means market order after trigger on OKX")] = "-1",
    json_output: JsonOpt = False,
) -> None:
    plan = _build_plan(exchange, symbol, side, size, take_profit, stop_loss, margin_mode, trigger_px_type, order_px)
    if json_output:
        print_json(plan)
        return
    _print_plan(plan)


def risk_bracket(
    exchange: Annotated[str, typer.Argument(help="currently only okx")],
    symbol: Annotated[str, typer.Argument(help="OKX instrument id, e.g. BTC-USDT-SWAP")],
    side: Annotated[str, typer.Argument(help="current position side: long/short")],
    size: Annotated[float, typer.Argument(help="position size to close")],
    take_profit: Annotated[float | None, typer.Option("--take-profit", help="take-profit trigger price")] = None,
    stop_loss: Annotated[float | None, typer.Option("--stop-loss", help="stop-loss trigger price")] = None,
    margin_mode: Annotated[str, typer.Option("--margin-mode", help="cross/isolated")] = "cross",
    trigger_px_type: Annotated[str, typer.Option("--trigger-px-type", help="last/index/mark")] = "last",
    order_px: Annotated[str, typer.Option("--order-px", help="-1 means market order after trigger on OKX")] = "-1",
    live: Annotated[bool, typer.Option("--live/--dry-run", help="place live orders only with --live")] = False,
    confirm: Annotated[str, typer.Option("--confirm", help="exact confirmation phrase from risk plan")] = "",
    json_output: JsonOpt = False,
) -> None:
    plan = _build_plan(exchange, symbol, side, size, take_profit, stop_loss, margin_mode, trigger_px_type, order_px)
    if not live:
        if json_output:
            print_json(plan)
            return
        _print_plan(plan)
        return
    expected = plan["confirm_phrase"]
    if str(confirm or "").strip() != expected:
        raise typer.BadParameter(f"live bracket confirmation mismatch; expected {expected}", param_hint="--confirm")
    client = build_ccxt_client("okx", "swap", require_private=True)
    try:
        payload = place_okx_bracket_orders(client, plan)
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns concise redacted exchange errors.
        raise typer.BadParameter(redact_text(f"{type(exc).__name__}: {exc}")) from exc
    finally:
        close_client(client)
    print_json(payload) if json_output else _print_live_result(payload)


def risk_orders(
    exchange: Annotated[str, typer.Argument(help="currently only okx")],
    symbol: Annotated[str | None, typer.Argument(help="optional OKX instrument id")] = None,
    json_output: JsonOpt = False,
) -> None:
    _validate_okx(exchange)
    client = build_ccxt_client("okx", "swap", require_private=True)
    try:
        payload = fetch_okx_algo_orders(client, symbol)
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns concise redacted exchange errors.
        raise typer.BadParameter(redact_text(f"{type(exc).__name__}: {exc}")) from exc
    finally:
        close_client(client)
    print_json(payload) if json_output else _print_algo_orders(payload)


def risk_cancel(
    exchange: Annotated[str, typer.Argument(help="currently only okx")],
    symbol: Annotated[str, typer.Argument(help="OKX instrument id, e.g. BTC-USDT-SWAP")],
    algo_ids: Annotated[list[str], typer.Argument(help="one or more OKX algoId values")],
    confirm: Annotated[str, typer.Option("--confirm", help="exact confirmation phrase")] = "",
    json_output: JsonOpt = False,
) -> None:
    _validate_okx(exchange)
    expected = f"LIVE_CANCEL_ALGOS:okx:{str(symbol).strip().upper()}:{','.join(algo_ids)}"
    if str(confirm or "").strip() != expected:
        raise typer.BadParameter(f"cancel confirmation mismatch; expected {expected}", param_hint="--confirm")
    client = build_ccxt_client("okx", "swap", require_private=True)
    try:
        payload = cancel_okx_algo_orders(client, symbol, algo_ids)
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns concise redacted exchange errors.
        raise typer.BadParameter(redact_text(f"{type(exc).__name__}: {exc}")) from exc
    finally:
        close_client(client)
    print_json(payload) if json_output else _print_live_result(payload)


def _build_plan(
    exchange: str,
    symbol: str,
    side: str,
    size: float,
    take_profit: float | None,
    stop_loss: float | None,
    margin_mode: str,
    trigger_px_type: str,
    order_px: str,
) -> dict:
    try:
        return build_okx_bracket_plan(
            exchange,
            symbol,
            side,
            size,
            take_profit=take_profit,
            stop_loss=stop_loss,
            margin_mode=margin_mode,
            trigger_px_type=trigger_px_type,
            order_px=order_px,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _validate_okx(exchange: str) -> None:
    if str(exchange or "").strip().lower() != "okx":
        raise typer.BadParameter("risk commands currently support only okx", param_hint="exchange")


def _print_plan(plan: dict) -> None:
    print(f"OKX risk bracket plan for {plan['symbol']} {plan['position_side']} size={plan['size']}")
    for order in plan.get("algo_orders") or []:
        payload = order["payload"]
        trigger = payload.get("tpTriggerPx") or payload.get("slTriggerPx")
        print(f"- {order['kind']}: {payload['side']} reduce-only at trigger {trigger}, orderPx={payload.get('tpOrdPx') or payload.get('slOrdPx')}")
    print(f"confirm: {plan['confirm_phrase']}")


def _print_live_result(payload: dict) -> None:
    print_json(payload)


def _print_algo_orders(payload: dict) -> None:
    print_json(payload)
