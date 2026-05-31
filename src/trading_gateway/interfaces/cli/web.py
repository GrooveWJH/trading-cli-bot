from __future__ import annotations

from typing import Annotated

import typer

from trading_gateway.interfaces.cli import help as cli_help
from trading_gateway.interfaces.web.server import run_web


def register_web_command(app: typer.Typer) -> None:
    app.command("web", help=cli_help.WEB)(web)


def web(
    host: Annotated[str, typer.Option("--host", help="bind host; localhost is recommended")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="dashboard port")] = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="open browser after startup")] = True,
    reload: Annotated[bool, typer.Option("--reload", help="reload web server during development")] = False,
) -> None:
    run_web(host, port, open_browser=open_browser, reload=reload)
