from __future__ import annotations

import webbrowser
from importlib.util import find_spec

import typer

from trading_gateway.interfaces.web.runtime import credential_presence
from trading_gateway.app.config import get_gateway_config


def run_web(host: str, port: int, *, open_browser: bool, reload: bool) -> None:
    _require_web_deps()
    import uvicorn

    config = get_gateway_config()
    url = f"http://{host}:{port}"
    typer.echo(f"Trading Gateway web: {url}")
    typer.echo(f"config: {config.path}")
    typer.echo(f"env: {config.dotenv_path}")
    typer.echo(f"credentials: {_credential_summary()}")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(
        "trading_gateway.interfaces.web.api:create_web_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


def _require_web_deps() -> None:
    missing = [name for name in ("fastapi", "uvicorn") if find_spec(name) is None]
    if missing:
        names = ", ".join(missing)
        raise typer.BadParameter(f"Trading Gateway web requires {names}. Run: bash scripts/dev/setup.sh", param_hint="web")


def _credential_summary() -> str:
    rows = []
    for exchange, fields in credential_presence().items():
        state = "present" if fields.get("api_key") and fields.get("api_secret") else "missing"
        rows.append(f"{exchange}={state}")
    return " ".join(rows)
