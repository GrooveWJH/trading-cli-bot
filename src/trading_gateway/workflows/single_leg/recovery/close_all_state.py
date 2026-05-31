from __future__ import annotations

from typing import Any

from trading_gateway.adapters.exchanges.positions import target_state
from trading_gateway.app.config import get_gateway_config


def close_all_reached(state: dict[str, Any]) -> bool:
    return float(state.get("remaining_quote_usdt") or 0) <= get_gateway_config().perp_execution.target_tolerance_quote_usdt


def close_all_state(client: Any, plan: dict[str, Any], positions: list[dict[str, Any]], current: float) -> dict[str, float]:
    state = target_state(current, 0.0, 0.0)
    state["remaining_quote_usdt"] = remaining_quote_usdt(client, plan, positions, current)
    return state


def remaining_quote_usdt(client: Any, plan: dict[str, Any], positions: list[dict[str, Any]], current: float) -> float:
    price = position_mark_price(positions) or ticker_price(client, plan["symbol"]) or float(plan.get("last_price") or 0)
    return float(f"{abs(current * price):.12g}") if price > 0 else 0.0


def position_mark_price(positions: list[dict[str, Any]]) -> float:
    for row in positions:
        for value in (row.get("markPrice"), row.get("mark_price"), (row.get("info") or {}).get("markPrice"), (row.get("info") or {}).get("markPx")):
            try:
                price = float(value or 0)
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price
    return 0.0


def ticker_price(client: Any, symbol: str) -> float:
    try:
        ticker = client.fetch_ticker(symbol) or {}
    except Exception:  # noqa: BLE001
        return 0.0
    for key in ("last", "mark", "close", "bid", "ask"):
        try:
            price = float(ticker.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return 0.0
