from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SingleLegIntent:
    exchange: str
    market: str
    action: str
    symbol: str
    quote_usdt: float | None = None
    bbo: bool = False

    def __post_init__(self) -> None:
        market = clean_value(self.market)
        action = clean_value(self.action)
        exchange = clean_value(self.exchange)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "action", action)
        if market not in {"spot", "perp"}:
            raise ValueError("market must be spot or perp")
        actions = {"buy", "sell"} if market == "spot" else {"open-long", "open-short", "close-long", "close-short"}
        if action == "close-shot":
            raise ValueError("unsupported perp action: close-shot; did you mean close-short?")
        if action not in actions:
            raise ValueError(f"unsupported {market} action: {action}")
        if market == "spot" and action == "buy" and self.quote_usdt is None:
            raise ValueError("quote_usdt is required for spot buy")
        if self.quote_usdt is not None and float(self.quote_usdt) <= 0:
            raise ValueError("quote_usdt must be positive")


def clean_value(value: str) -> str:
    return str(value or "").strip().lower()
