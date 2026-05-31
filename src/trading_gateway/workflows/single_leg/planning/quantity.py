from __future__ import annotations

from math import ceil, floor
from typing import Any

from trading_gateway.adapters.exchanges.rules import amount_step, min_amount, min_cost_quote

from .intent import SingleLegIntent


def build_quantity_plan(
    client: Any,
    symbol: str,
    market: dict[str, Any],
    intent: SingleLegIntent,
    last: float,
    contract_size: float,
) -> dict[str, float | bool]:
    return build_quantity_core(
        client,
        symbol,
        market,
        market_kind=intent.market,
        quote_usdt=intent.quote_usdt,
        last=last,
        contract_size=contract_size,
    )


def build_perp_minimum_plan(
    client: Any,
    symbol: str,
    market: dict[str, Any],
    *,
    quote_usdt: float,
    last: float,
    contract_size: float,
) -> dict[str, float | bool]:
    return build_quantity_core(
        client,
        symbol,
        market,
        market_kind="perp",
        quote_usdt=quote_usdt,
        last=last,
        contract_size=contract_size,
    )


def base_to_precision_amount(client: Any, symbol: str, base_qty: float, market: str, contract_size: float) -> float:
    order_amount = base_qty / contract_size if market == "perp" and contract_size > 0 else base_qty
    return amount_to_precision(client, symbol, order_amount)


def amount_to_precision(client: Any, symbol: str, value: float) -> float:
    method = getattr(client, "amount_to_precision", None)
    return float(method(symbol, value)) if callable(method) else value


def floor_step(value: float, step: float) -> float:
    return floor(value / step) * step if step > 0 else value


def ceil_step(value: float, step: float) -> float:
    return ceil(value / step) * step if step > 0 else value


def clean_number(value: float) -> float:
    return float(f"{float(value):.12g}")


def build_quantity_core(
    client: Any,
    symbol: str,
    market: dict[str, Any],
    *,
    market_kind: str,
    quote_usdt: float | None,
    last: float,
    contract_size: float,
) -> dict[str, float | bool]:
    base_step = amount_step(market) * (contract_size if market_kind == "perp" else 1.0)
    min_qty = min_amount(market) * (contract_size if market_kind == "perp" else 1.0)
    min_cost = min_cost_quote(market)
    min_cost_qty = ceil_step(min_cost / last, base_step) if min_cost > 0 else 0.0
    min_exec_qty = max(min_qty, min_cost_qty)
    min_exec_quote = max(min_exec_qty * last, min_cost)
    quote = float(quote_usdt) if quote_usdt is not None else min_exec_quote
    requested_qty = floor_step(quote / last, base_step)
    blocked = quote < min_exec_quote or requested_qty < min_exec_qty
    base_qty = min_exec_qty if blocked else requested_qty
    order_amount = base_to_precision_amount(client, symbol, base_qty, market_kind, contract_size)
    base_qty = order_amount * contract_size if market_kind == "perp" else order_amount
    return {
        "base_quantity": clean_number(base_qty),
        "order_amount": clean_number(order_amount),
        "actual_quote": clean_number(base_qty * last),
        "min_executable_quote": clean_number(min_exec_quote),
        "min_executable_quantity": clean_number(min_exec_qty),
        "base_step": clean_number(base_step),
        "below_minimum": blocked,
    }
