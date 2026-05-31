from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

import typer

from trading_gateway.app.config import get_gateway_config
from trading_gateway.interfaces.cli import help as cli_help
from trading_gateway.interfaces.cli.commands.pair_workflow import _wait_for_job, pair_close_plan, pair_close_resume, pair_close_run, pair_close_status, pair_plan, pair_resume, pair_run, pair_status
from trading_gateway.interfaces.cli.commands.planning import build_single_leg_cli_plan
from trading_gateway.interfaces.cli.presenters import print_plan_brief, print_run_brief
from trading_gateway.interfaces.daemon.client import DaemonClientError, daemon_http_post, ensure_daemon_ready_for_live
from trading_gateway.support.formatting import print_json
JsonOpt = Annotated[bool, typer.Option("--json", help="print machine-readable JSON")]


def register_lab_commands(app: typer.Typer) -> None:
    app.command("plan", help=cli_help.LAB_PLAN)(lab_plan)
    app.command("run", help=cli_help.LAB_RUN)(lab_run)
    app.command("pair-plan", help=cli_help.PAIR_PLAN)(pair_plan)
    app.command("pair-run", help=cli_help.PAIR_RUN)(pair_run)
    app.command("pair-close-plan", help=cli_help.PAIR_CLOSE_PLAN)(pair_close_plan)
    app.command("pair-close-run", help=cli_help.PAIR_CLOSE_RUN)(pair_close_run)
    app.command("pair-status", help=cli_help.PAIR_STATUS)(pair_status)
    app.command("pair-resume", help=cli_help.PAIR_RESUME)(pair_resume)
    app.command("pair-close-status", help=cli_help.PAIR_STATUS)(pair_close_status)
    app.command("pair-close-resume", help=cli_help.PAIR_RESUME)(pair_close_resume)


def lab_plan(
    exchange: Annotated[str, typer.Argument(help="exchange: binance/okx/gate/mexc")],
    market: Annotated[str, typer.Argument(help="spot/perp")],
    action: Annotated[str, typer.Argument(help="spot: buy/sell; perp: open-long/open-short/close-long/close-short")],
    symbol: Annotated[str, typer.Argument(help="route universe symbol, e.g. SOL/USDT")],
    quote_usdt: Annotated[float | None, typer.Argument(help="quote USDT; optional for close actions")] = None,
    bbo: Annotated[bool, typer.Option("--bbo", help="use configured maker/BBO order")] = False,
    last_price: Annotated[float | None, typer.Option("--last-price", help="static price for dry planning/tests")] = None,
    json_output: JsonOpt = False,
) -> None:
    started = perf_counter()
    plan = build_lab_plan(exchange, market, action, symbol, quote_usdt, bbo, last_price)
    query_ms = _elapsed_ms(started)
    print_plan_brief(plan, query_ms)
    if json_output:
        print_json({"mode": "single_leg_plan", "query_ms": query_ms, "plan": plan})


def lab_run(
    exchange: Annotated[str, typer.Argument(help="exchange: binance/okx/gate/mexc")],
    market: Annotated[str, typer.Argument(help="spot/perp")],
    action: Annotated[str, typer.Argument(help="spot: buy/sell; perp: open-long/open-short/close-long/close-short")],
    symbol: Annotated[str, typer.Argument(help="route universe symbol, e.g. SOL/USDT")],
    quote_usdt: Annotated[float | None, typer.Argument(help="quote USDT; optional for close actions")] = None,
    bbo: Annotated[bool, typer.Option("--bbo", help="use configured maker/BBO order")] = False,
    confirm: Annotated[str, typer.Option("--confirm", help="exact live confirmation phrase")] = "",
    timeout_sec: Annotated[float | None, typer.Option("--timeout-sec", help="override config order_timeout_sec")] = None,
    max_requotes: Annotated[int | None, typer.Option("--max-requotes", help="override config max_requotes")] = None,
    json_output: JsonOpt = False,
) -> None:
    started = perf_counter()
    try:
        ensure_daemon_ready_for_live(config_file=get_gateway_config().path)
        build_lab_plan(exchange, market, action, symbol, quote_usdt, bbo, None)
        body = {
            "exchange": exchange,
            "market": market,
            "action": action,
            "symbol": symbol,
            "quote_usdt": quote_usdt,
            "bbo": bbo,
            "confirm": confirm,
            "timeout_sec": timeout_sec,
            "max_requotes": max_requotes,
        }
        started_job = daemon_http_post("/api/lab/run", body)
        payload = _wait_for_job(started_job["job_id"])
    except DaemonClientError as exc:
        raise typer.BadParameter(str(exc), param_hint="daemon") from exc
    payload["query_ms"] = _elapsed_ms(started)
    print_run_brief(payload)
    if json_output:
        print_json(payload)
    if payload.get("final_status") in {"blocked", "submit_error", "target_not_reached", "asset_target_not_reached", "close_all_pending", "force_close_failed"}:
        raise typer.Exit(1)


def build_lab_plan(
    exchange: str,
    market: str,
    action: str,
    symbol: str,
    quote_usdt: float | None,
    bbo: bool,
    last_price: float | None,
) -> dict[str, Any]:
    try:
        return build_single_leg_cli_plan(
            exchange=exchange,
            market=market,
            action=action,
            symbol=symbol,
            quote_usdt=quote_usdt,
            bbo=bbo,
            last_price=last_price,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="ACTION") from exc


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
