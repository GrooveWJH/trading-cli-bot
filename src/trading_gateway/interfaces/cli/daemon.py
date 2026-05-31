from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from trading_gateway.interfaces.daemon.client import DaemonClientError, daemon_http_get, read_daemon_metadata
from trading_gateway.interfaces.daemon.server import start_daemon, stop_daemon
from trading_gateway.support.formatting import print_json


def register_daemon_commands(app: typer.Typer) -> None:
    daemon_app = typer.Typer(add_completion=False, help="Manage the local Trading Gateway live daemon.")
    daemon_app.command("start", help="Start the localhost live trading daemon.")(daemon_start)
    daemon_app.command("status", help="Show daemon reachability and per-route health.")(daemon_status)
    daemon_app.command("stop", help="Stop the localhost live trading daemon.")(daemon_stop)
    app.add_typer(daemon_app, name="daemon")


def daemon_start() -> None:
    start_daemon()


def daemon_stop() -> None:
    stop_daemon()


def daemon_status(
    json_output: Annotated[bool, typer.Option("--json", help="print machine-readable JSON")] = False,
) -> None:
    metadata = read_daemon_metadata()
    try:
        payload = daemon_http_get("/api/daemon/status", metadata=metadata)
    except DaemonClientError:
        payload = {
            "mode": "trading_gateway_daemon",
            "status": "unreachable",
            "pid": None if not metadata else metadata.get("pid"),
            "host": None if not metadata else metadata.get("host"),
            "port": None if not metadata else metadata.get("port"),
            "config_file": None if not metadata else metadata.get("config_file"),
            "active_live_job": None,
            "routes": [],
        }
    if json_output:
        print_json(payload)
        return
    _print_daemon_status(payload)


def _print_daemon_status(payload: dict[str, Any]) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("status", str(payload.get("status")))
    table.add_row("pid", _text(payload.get("pid")))
    table.add_row("host", _text(payload.get("host")))
    table.add_row("port", _text(payload.get("port")))
    table.add_row("config", _text(payload.get("config_file")))
    table.add_row("active_live_job", _text((payload.get("active_live_job") or {}).get("job_id")))
    route_table = Table(show_header=True, header_style="bold")
    route_table.add_column("Route")
    route_table.add_column("Status")
    route_table.add_column("LastRefreshAgeSec")
    route_table.add_column("LastError")
    for row in payload.get("routes") or []:
        route_table.add_row(
            _text(row.get("route")),
            _text(row.get("status")),
            _text(row.get("last_private_refresh_age_sec")),
            _text(row.get("last_error")),
        )
    Console(stderr=True, width=120).print(Panel(table, title="Trading Gateway Daemon"))
    if payload.get("routes"):
        Console(stderr=True, width=120).print(route_table)


def _text(value: Any) -> str:
    return "-" if value is None else str(value)
