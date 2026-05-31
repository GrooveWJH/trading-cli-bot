from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from trading_gateway.app.config import get_gateway_config
from trading_gateway.workflows.overview.planning_account_state import AccountStateUsage, daemon_cache_usage, exchange_fetch_usage


@dataclass(frozen=True)
class CachedAccountState:
    balance: dict[str, Any]
    positions: list[dict[str, Any]]
    refreshed_at: float


class DaemonAccountStateStore:
    def __init__(self) -> None:
        self._config = get_gateway_config()

    def usage_for_cache(self, refreshed_at: float | None) -> AccountStateUsage:
        age_sec = None if refreshed_at is None else max(0.0, time.time() - refreshed_at)
        return daemon_cache_usage(age_sec=age_sec)

    def usage_for_fetch(self, reason: str | None) -> AccountStateUsage:
        return exchange_fetch_usage(reason)

    def cache_fresh(self, refreshed_at: float | None) -> bool:
        if refreshed_at is None:
            return False
        return max(0.0, time.time() - refreshed_at) <= self._config.planning.account_state_max_age_sec
