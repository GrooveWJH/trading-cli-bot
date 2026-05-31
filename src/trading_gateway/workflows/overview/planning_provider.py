from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from trading_gateway.app.config import get_gateway_config
from trading_gateway.workflows.overview.planning_account_state import AccountStateUsage, daemon_cache_usage, exchange_fetch_usage


Fetcher = Callable[[], tuple[dict[str, Any], list[dict[str, Any]]]]


@dataclass(frozen=True)
class PlanningAccountState:
    balance: dict[str, Any]
    positions: list[dict[str, Any]]
    usage: AccountStateUsage


def resolve_planning_account_state(
    *,
    cached_reader: Callable[[], dict[str, Any]],
    fetcher: Fetcher,
) -> PlanningAccountState:
    config = get_gateway_config().planning
    try:
        cached = cached_reader()
        return PlanningAccountState(
            balance=dict(cached.get("balance") or {}),
            positions=list(cached.get("positions") or []),
            usage=daemon_cache_usage(
                age_sec=_age_from_refreshed_at(cached.get("refreshed_at")),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - planning fallback reasons are user-facing state.
        reason = str(exc) or "daemon_unavailable"
        if not config.allow_direct_exchange_fallback:
            raise
        balance, positions = fetcher()
        return PlanningAccountState(
            balance=balance,
            positions=positions,
            usage=exchange_fetch_usage(reason),
        )


def _age_from_refreshed_at(refreshed_at: Any) -> float | None:
    if refreshed_at is None:
        return None
    try:
        from time import time

        return max(0.0, time() - float(refreshed_at))
    except (TypeError, ValueError):
        return None
