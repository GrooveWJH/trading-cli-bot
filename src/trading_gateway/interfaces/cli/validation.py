from __future__ import annotations

import typer

from trading_gateway.domain.models import PUBLIC_MARKET_TYPES, SUPPORTED_EXCHANGES, normalize_market


def validate_exchange(value: str) -> None:
    if value not in SUPPORTED_EXCHANGES:
        raise typer.BadParameter(f"exchange must be one of {', '.join(SUPPORTED_EXCHANGES)}", param_hint="--exchange")


def validate_market(value: str) -> None:
    try:
        normalize_market(value)
    except ValueError as exc:
        raise typer.BadParameter(f"market must be one of {', '.join(PUBLIC_MARKET_TYPES)}", param_hint="--market") from exc
