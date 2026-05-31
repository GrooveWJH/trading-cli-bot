from __future__ import annotations

from math import ceil, floor
from typing import Any


def plan_quantity_from_rules(client: Any, symbol: str, market: dict[str, Any], quote: float, last: float, *, spot_buy: bool) -> dict[str, float]:
    step = amount_step(market)
    min_exec = min_executable(market, last)
    raw_qty = quote / last
    requested_qty = raw_qty if spot_buy else floor_step(raw_qty, step)
    min_exec_qty = min_exec["quantity"]
    min_exec_quote = min_exec["quote"]
    blocked = quote < min_exec_quote or (not spot_buy and requested_qty < min_exec_qty)
    planned_qty = min_exec_qty if blocked else requested_qty
    qty = amount_to_precision(client, symbol, planned_qty)
    actual_quote = quote if spot_buy else qty * last
    return {
        "quantity": _clean_number(qty),
        "actual_quote": _clean_number(actual_quote),
        "min_executable_quote": _clean_number(min_exec_quote),
        "min_executable_quantity": _clean_number(min_exec_qty),
        "requested_quantity": _clean_number(requested_qty),
        "below_minimum": blocked,
    }


def min_executable(market: dict[str, Any], last: float) -> dict[str, float]:
    step = amount_step(market)
    min_qty = min_amount(market)
    min_cost = min_cost_quote(market)
    min_cost_qty = ceil_step(min_cost / last, step) if min_cost > 0 else 0.0
    quantity = max(min_qty, min_cost_qty)
    return {"quantity": _clean_number(quantity), "quote": _clean_number(max(quantity * last, min_cost))}


def min_amount(market: dict[str, Any]) -> float:
    value = _positive(((market.get("limits") or {}).get("amount") or {}).get("min"))
    if value > 0:
        return value
    value = _filter_float(market, ("LOT_SIZE", "MARKET_LOT_SIZE"), "minQty")
    if value > 0:
        return value
    raise ValueError("minimum amount unavailable")


def min_cost_quote(market: dict[str, Any]) -> float:
    value = _positive(((market.get("limits") or {}).get("cost") or {}).get("min"))
    if value > 0:
        return value
    return _filter_float(market, ("MIN_NOTIONAL", "NOTIONAL"), "minNotional")


def amount_step(market: dict[str, Any]) -> float:
    value = _filter_float(market, ("LOT_SIZE", "MARKET_LOT_SIZE"), "stepSize")
    if value > 0:
        return value
    precision = (market.get("precision") or {}).get("amount")
    if isinstance(precision, int):
        return 10 ** (-precision)
    if isinstance(precision, float) and precision > 0:
        return precision if precision <= 1 else 10 ** (-int(precision))
    return min_amount(market)


def floor_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return floor(value / step) * step


def ceil_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return ceil(value / step) * step


def amount_to_precision(client: Any, symbol: str, value: float) -> float:
    method = getattr(client, "amount_to_precision", None)
    return float(method(symbol, value)) if callable(method) else value


def _filter_float(market: dict[str, Any], filter_types: tuple[str, ...], key: str) -> float:
    for row in ((market.get("info") or {}).get("filters") or []):
        if row.get("filterType") in filter_types:
            value = _positive(row.get(key))
            if value > 0:
                return value
    return 0.0


def _positive(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _clean_number(value: float) -> float:
    return float(f"{float(value):.12g}")
