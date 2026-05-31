from __future__ import annotations

from importlib.util import find_spec

import typer

from trading_gateway.interfaces.web.api import create_app


def main(
    host: str = "127.0.0.1",
    port: int = 8766,
) -> None:
    _require_web_deps()
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, reload=False)


def _require_web_deps() -> None:
    missing = [name for name in ("fastapi", "uvicorn") if find_spec(name) is None]
    if missing:
        names = ", ".join(missing)
        raise typer.BadParameter(f"Trading Gateway daemon requires {names}. Run: bash scripts/dev/setup.sh", param_hint="daemon")


if __name__ == "__main__":
    typer.run(main)
