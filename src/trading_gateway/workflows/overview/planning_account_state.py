from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccountStateUsage:
    account_state_source: str
    account_state_age_sec: float | None
    market_data_source: str
    fallback_reason: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "account_state_source": self.account_state_source,
            "account_state_age_sec": self.account_state_age_sec,
            "market_data_source": self.market_data_source,
            "fallback_reason": self.fallback_reason,
        }


def daemon_cache_usage(*, age_sec: float | None, fallback_reason: str | None = None) -> AccountStateUsage:
    return AccountStateUsage(
        account_state_source="daemon_cache",
        account_state_age_sec=age_sec,
        market_data_source="live",
        fallback_reason=fallback_reason,
    )


def exchange_fetch_usage(reason: str | None) -> AccountStateUsage:
    return AccountStateUsage(
        account_state_source="exchange_fetch",
        account_state_age_sec=None,
        market_data_source="live",
        fallback_reason=reason,
    )
