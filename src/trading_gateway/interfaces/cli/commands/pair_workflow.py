from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

import typer

from trading_gateway.app.config import get_gateway_config
from trading_gateway.infrastructure.exchange.factory import close_client
from trading_gateway.interfaces.cli.commands.planning import build_pair_cli_plan, build_pair_close_cli_plan, cli_pair_client
from trading_gateway.interfaces.cli.presenters import print_execution_progress, print_pair_plan_brief, print_pair_run_brief, print_pair_status_brief
from trading_gateway.interfaces.daemon.client import DaemonClientError, daemon_http_get, daemon_http_post, ensure_daemon_ready_for_live
from trading_gateway.support.formatting import print_json
from trading_gateway.workflows.pair_trade.execution import resume_close_execution, resume_live_execution
from trading_gateway.workflows.pair_trade.journaling.journal import load_pair_journal, validate_pair_journal
from trading_gateway.workflows.pair_trade.recovery.status import build_pair_status

JsonOpt = Annotated[bool, typer.Option("--json", help="print machine-readable JSON")]


def pair_plan(
    spot_exchange: Annotated[str, typer.Argument(help="spot exchange: binance/okx/gate/mexc")],
    perp_exchange: Annotated[str, typer.Argument(help="perp exchange: binance/okx/gate/mexc")],
    symbol: Annotated[str, typer.Argument(help="route universe symbol, e.g. SOL/USDT")],
    quote_usdt: Annotated[float, typer.Argument(help="quote USDT used to derive the shared base quantity")],
    last_price: Annotated[float | None, typer.Option("--last-price", help="static price for dry planning/tests")] = None,
    json_output: JsonOpt = False,
) -> None:
    _print_pair_plan(
        build_pair_cli_plan(spot_exchange=spot_exchange, perp_exchange=perp_exchange, symbol=symbol, quote_usdt=quote_usdt, last_price=last_price, pair_client=pair_client),
        "pair_trading_plan",
        json_output,
    )


def pair_close_plan(
    spot_exchange: Annotated[str, typer.Argument(help="spot exchange: binance/okx/gate/mexc")],
    perp_exchange: Annotated[str, typer.Argument(help="perp exchange: binance/okx/gate/mexc")],
    symbol: Annotated[str, typer.Argument(help="route universe symbol, e.g. SOL/USDT")],
    last_price: Annotated[float | None, typer.Option("--last-price", help="static price for dry planning/tests")] = None,
    json_output: JsonOpt = False,
) -> None:
    _print_pair_plan(
        build_pair_close_cli_plan(spot_exchange=spot_exchange, perp_exchange=perp_exchange, symbol=symbol, last_price=last_price, pair_client=pair_client),
        "pair_close_plan",
        json_output,
    )


def pair_run(
    spot_exchange: Annotated[str, typer.Argument(help="spot exchange: binance/okx/gate/mexc")],
    perp_exchange: Annotated[str, typer.Argument(help="perp exchange: binance/okx/gate/mexc")],
    symbol: Annotated[str, typer.Argument(help="route universe symbol, e.g. SOL/USDT")],
    quote_usdt: Annotated[float, typer.Argument(help="quote USDT used to derive the shared base quantity")],
    confirm: Annotated[str, typer.Option("--confirm", help="exact live confirmation phrase")] = "",
    timeout_sec: Annotated[float | None, typer.Option("--timeout-sec", help="override pair order timeout")] = None,
    max_requotes: Annotated[int | None, typer.Option("--max-requotes", help="override normal pair max_requotes")] = None,
    json_output: JsonOpt = False,
) -> None:
    _run_pair_job(
        "/api/pair/run",
        {
            "spot_exchange": spot_exchange,
            "perp_exchange": perp_exchange,
            "symbol": symbol,
            "quote_usdt": quote_usdt,
            "confirm": confirm,
            "timeout_sec": timeout_sec,
            "max_requotes": max_requotes,
        },
        json_output,
    )


def pair_close_run(
    spot_exchange: Annotated[str, typer.Argument(help="spot exchange: binance/okx/gate/mexc")],
    perp_exchange: Annotated[str, typer.Argument(help="perp exchange: binance/okx/gate/mexc")],
    symbol: Annotated[str, typer.Argument(help="route universe symbol, e.g. SOL/USDT")],
    confirm: Annotated[str, typer.Option("--confirm", help="exact live confirmation phrase")] = "",
    timeout_sec: Annotated[float | None, typer.Option("--timeout-sec", help="override pair order timeout")] = None,
    max_requotes: Annotated[int | None, typer.Option("--max-requotes", help="override normal pair max_requotes")] = None,
    json_output: JsonOpt = False,
) -> None:
    _run_pair_job(
        "/api/pair/close/run",
        {
            "spot_exchange": spot_exchange,
            "perp_exchange": perp_exchange,
            "symbol": symbol,
            "confirm": confirm,
            "timeout_sec": timeout_sec,
            "max_requotes": max_requotes,
        },
        json_output,
    )


def pair_status(
    pair_id: Annotated[str, typer.Argument(help="pair id returned by pair-run, e.g. aspair_xxx")],
    json_output: JsonOpt = False,
) -> None:
    payload = _load_pair_status(pair_id)
    print_pair_status_brief(payload)
    if json_output:
        print_json(payload)
    if payload.get("final_status") != "pair_target_reached":
        raise typer.Exit(1)


def pair_close_status(
    pair_id: Annotated[str, typer.Argument(help="pair id returned by pair-close-run, e.g. aspair_xxx")],
    json_output: JsonOpt = False,
) -> None:
    pair_status(pair_id, json_output=json_output)


def pair_resume(
    pair_id: Annotated[str, typer.Argument(help="pair id returned by pair-run, e.g. aspair_xxx")],
    confirm: Annotated[str, typer.Option("--confirm", help="original pair live confirmation phrase")] = "",
    timeout_sec: Annotated[float | None, typer.Option("--timeout-sec", help="override pair order timeout")] = None,
    max_requotes: Annotated[int | None, typer.Option("--max-requotes", help="override resume max_requotes")] = None,
    json_output: JsonOpt = False,
) -> None:
    _resume_pair(pair_id, confirm, timeout_sec, max_requotes, json_output, resume_live_execution)


def pair_close_resume(
    pair_id: Annotated[str, typer.Argument(help="pair id returned by pair-close-run, e.g. aspair_xxx")],
    confirm: Annotated[str, typer.Option("--confirm", help="original pair close live confirmation phrase")] = "",
    timeout_sec: Annotated[float | None, typer.Option("--timeout-sec", help="override pair order timeout")] = None,
    max_requotes: Annotated[int | None, typer.Option("--max-requotes", help="override resume max_requotes")] = None,
    json_output: JsonOpt = False,
) -> None:
    _resume_pair(pair_id, confirm, timeout_sec, max_requotes, json_output, resume_close_execution)


def pair_client(exchange: str, market: str, symbol: str, last_price: float | None, *, private: bool) -> Any:
    return cli_pair_client(exchange, market, symbol, last_price, private=private)


def _print_pair_plan(plan: dict[str, Any], mode: str, json_output: bool) -> None:
    started = perf_counter()
    query_ms = _elapsed_ms(started)
    print_pair_plan_brief(plan, query_ms)
    if json_output:
        print_json({"mode": mode, "query_ms": query_ms, "plan": plan})


def _run_pair_job(path: str, body: dict[str, Any], json_output: bool) -> None:
    started = perf_counter()
    try:
        ensure_daemon_ready_for_live(config_file=get_gateway_config().path)
        payload = _wait_for_job(daemon_http_post(path, body)["job_id"])
    except DaemonClientError as exc:
        raise typer.BadParameter(str(exc), param_hint="daemon") from exc
    payload["query_ms"] = _elapsed_ms(started)
    print_pair_run_brief(payload)
    if json_output:
        print_json(payload)
    if payload.get("final_status") != "pair_target_reached":
        raise typer.Exit(1)


def _load_pair_status(pair_id: str) -> dict[str, Any]:
    started = perf_counter()
    plan, spot, perp = _load_pair_clients(pair_id)
    try:
        payload = build_pair_status(spot, perp, pair_id)
    finally:
        close_client(spot)
        close_client(perp)
    payload["query_ms"] = _elapsed_ms(started)
    return payload


def _resume_pair(
    pair_id: str,
    confirm: str,
    timeout_sec: float | None,
    max_requotes: int | None,
    json_output: bool,
    runner: Any,
) -> None:
    started = perf_counter()
    _, spot, perp = _load_pair_clients(pair_id)
    try:
        payload = runner(spot, perp, pair_id, confirm=confirm, timeout_sec=timeout_sec, normal_max_requotes=max_requotes, progress=print_execution_progress)
    finally:
        close_client(spot)
        close_client(perp)
    payload["query_ms"] = _elapsed_ms(started)
    print_pair_run_brief(payload)
    if json_output:
        print_json(payload)
    if payload.get("final_status") != "pair_target_reached":
        raise typer.Exit(1)


def _load_pair_clients(pair_id: str) -> tuple[dict[str, Any], Any, Any]:
    try:
        journal = load_pair_journal(pair_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="PAIR_ID") from exc
    validate_pair_journal(journal)
    plan = journal["plan"]
    return (
        plan,
        pair_client(plan["spot_exchange"], "spot", plan["canonical_symbol"], None, private=True),
        pair_client(plan["perp_exchange"], "perp", plan["perp_symbol"], None, private=True),
    )


def _wait_for_job(job_id: str) -> dict[str, Any]:
    seen = 0
    while True:
        job = daemon_http_get(f"/api/jobs/{job_id}")
        steps = job.get("steps") or []
        for step in steps[seen:]:
            print_execution_progress(step)
        seen = len(steps)
        if job.get("status") != "running":
            if job.get("status") == "completed":
                return job["result"]
            raise DaemonClientError(job.get("error") or "daemon live job failed")


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
