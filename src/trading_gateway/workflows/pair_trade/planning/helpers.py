from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_gateway.adapters.exchanges.positions import position_quantity
from trading_gateway.adapters.exchanges.rules import amount_step, amount_to_precision, floor_step, min_executable
from trading_gateway.adapters.exchanges.single_leg import adapter_for
from trading_gateway.domain.models import format_decimal
from trading_gateway.domain.route_universe import validate_trading_symbol
from trading_gateway.workflows.single_leg.planning.quantity import build_perp_minimum_plan


def market_for(adapter: Any, client: Any, resolution: Any) -> dict[str, Any]:
    return adapter.market_lookup(client, resolution)


def book_top(client: Any, symbol: str) -> dict[str, float]:
    book = client.fetch_order_book(symbol)
    bid = float((book.get("bids") or [[0]])[0][0] or 0)
    ask = float((book.get("asks") or [[0]])[0][0] or 0)
    if bid <= 0 or ask <= 0:
        raise ValueError(f"order book unavailable for {symbol}")
    return {"bid": bid, "ask": ask}


def reference_price(client: Any, symbol: str) -> float:
    ticker = client.fetch_ticker(symbol) or {}
    return positive_float(ticker.get("last") or ticker.get("mark") or ticker.get("bid") or ticker.get("ask"), "perp price")


def common_quantity(
    spot_client: Any,
    perp_client: Any,
    spot_symbol: str,
    perp_symbol: str,
    spot_market: dict[str, Any],
    perp_market: dict[str, Any],
    quote_usdt: float,
    reference_price_value: float,
    perp_contract_size: float,
) -> float:
    common_step = max(amount_step(spot_market), amount_step(perp_market) * perp_contract_size)
    raw = quote_usdt / reference_price_value
    floored = floor_step(raw, common_step)
    spot_qty = amount_to_precision(spot_client, spot_symbol, floored)
    perp_order_amount = floored / perp_contract_size if perp_contract_size > 0 else floored
    perp_qty = amount_to_precision(perp_client, perp_symbol, perp_order_amount) * perp_contract_size
    return min(spot_qty, perp_qty)


def minimums_for_pair(
    *,
    spot_client: Any,
    perp_client: Any,
    spot_symbol: str,
    perp_symbol: str,
    spot_market: dict[str, Any],
    perp_market: dict[str, Any],
    reference_price_value: float,
    quote_usdt: float,
    perp_contract_size: float,
) -> dict[str, Any]:
    spot_min = min_executable(spot_market, reference_price_value)
    perp_plan = build_perp_minimum_plan(
        perp_client,
        perp_symbol,
        perp_market,
        quote_usdt=quote_usdt,
        last=reference_price_value,
        contract_size=perp_contract_size,
    )
    spot_quote = float(spot_min["quote"])
    perp_quote = float(perp_plan["min_executable_quote"])
    effective_source = "spot" if spot_quote >= perp_quote else "perp"
    return {
        "spot": {
            "min_quantity": float(spot_min["quantity"]),
            "min_quote_usdt": spot_quote,
        },
        "perp": {
            "min_quantity": float(perp_plan["min_executable_quantity"]),
            "min_quote_usdt": perp_quote,
        },
        "effective_source": effective_source,
    }


def warnings_for_pair(
    *,
    spot_exchange: str,
    perp_exchange: str,
    canonical_symbol: str,
    quantity: float,
    min_quantity: float,
    quote_usdt: float,
    min_quote: float,
    effective_source: str,
    universe_path: str | Path | None,
    max_quote: float,
    spot_adapter: Any,
    perp_adapter: Any,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if universe_path is not None:
        for exchange, market in ((spot_exchange, "spot"), (perp_exchange, "perp")):
            result = validate_trading_symbol(canonical_symbol, market, exchange, universe_path)
            if not result["supported"]:
                warnings.append({"code": "symbol_not_supported", "message": result["reason"]})
    if quote_usdt < min_quote or quantity < min_quantity:
        warnings.append(
            {
                "code": "below_minimum_quantity_notional",
                "message": (
                    "requested quote is below pair minimum executable quote; "
                    f"effective_leg={effective_source}; min_executable_quote_usdt={format_decimal(min_quote)}"
                ),
            }
        )
    if quote_usdt > max_quote:
        warnings.append({"code": "above_lab_safety_cap", "message": "requested quote is above local lab safety cap"})
    for adapter in (spot_adapter, perp_adapter):
        if not adapter.supports_live():
            warnings.append({"code": "exchange_market_not_supported", "message": adapter.unsupported_reason()})
    return warnings


def spot_balances(client: Any, base_asset: str, quote_asset: str, *, payload: dict[str, Any] | None = None) -> dict[str, float]:
    source = payload if payload is not None else client.fetch_balance() if hasattr(client, "fetch_balance") else {}
    return {
        "base_free": balance_value(source, base_asset, "free"),
        "base_total": balance_value(source, base_asset, "total"),
        "quote_free": balance_value(source, quote_asset, "free"),
    }


def perp_quote_free(client: Any, quote_asset: str, *, payload: dict[str, Any] | None = None) -> float:
    source = payload if payload is not None else client.fetch_balance() if hasattr(client, "fetch_balance") else {}
    return balance_value(source, quote_asset, "free")


def balance_value(payload: dict[str, Any], asset: str, key: str) -> float:
    raw_row = payload.get(asset)
    row = raw_row if isinstance(raw_row, dict) else {}
    value = row.get(key)
    raw_bucket = payload.get(key)
    if value is None and isinstance(raw_bucket, dict):
        value = raw_bucket.get(asset)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def hedge_mode(client: Any) -> bool:
    for method_name in (
        "fapiPrivateGetPositionSideDual",
        "fapiprivate_get_positionside_dual",
        "privateGetAccountConfig",
        "private_get_account_config",
    ):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method() or {}
        except Exception:
            return False
        value = payload.get("dualSidePosition") or payload.get("posMode")
        if value is True or str(value).lower() in {"true", "long_short_mode"}:
            return True
    return False


def perp_min_executable(market: dict[str, Any], reference_price_value: float, contract_size: float) -> dict[str, float]:
    minimum = min_executable(market, reference_price_value)
    quantity = float(minimum["quantity"]) * contract_size
    quote = max(quantity * reference_price_value, float(minimum["quote"]))
    return {"quantity": quantity, "quote": quote}



def positive_float(value: Any, label: str) -> float:
    number = float(value or 0)
    if number <= 0:
        raise ValueError(f"{label} unavailable")
    return number


def confirm_phrase(spot_exchange: str, perp_exchange: str, canonical_symbol: str, quote_usdt: float) -> str:
    return f"LIVE_PAIR_OPEN:{spot_exchange}:{perp_exchange}:{canonical_symbol.replace('/', '')}:QUOTE_{format_decimal(quote_usdt)}"


def close_confirm_phrase(spot_exchange: str, perp_exchange: str, canonical_symbol: str) -> str:
    return f"LIVE_PAIR_CLOSE:{spot_exchange}:{perp_exchange}:{canonical_symbol.replace('/', '')}"


def position_short_quantity(client: Any, symbol: str, hedge: bool, *, positions: list[dict[str, Any]] | None = None) -> float:
    payload = positions if positions is not None else client.fetch_positions([symbol]) if hasattr(client, "fetch_positions") else []
    return position_quantity(payload, symbol, "short", hedge)


def pair_adapter(exchange: str, market: str) -> Any:
    return adapter_for(exchange, market)
