from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_gateway.adapters.exchanges.single_leg import adapter_for
from trading_gateway.app.config import get_gateway_config
from trading_gateway.domain.models import format_decimal
from trading_gateway.domain.route_universe import validate_trading_symbol
from trading_gateway.workflows.overview.planning_account_state import exchange_fetch_usage

from .intent import SingleLegIntent
from .preview import build_execution_preview
from .quantity import build_quantity_plan


def build_single_leg_trade_plan(
    client: Any,
    intent: SingleLegIntent,
    universe_path: str | Path | None = None,
    *,
    account_state: dict[str, Any] | None = None,
    planning_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = get_gateway_config()
    adapter = adapter_for(intent.exchange, intent.market)
    resolution = adapter.normalize_symbol(intent.symbol)
    market = adapter.market_lookup(client, resolution)
    trade_symbol = str(market.get("symbol") or resolution.ccxt_symbol)
    ticker = client.fetch_ticker(trade_symbol) or {}
    last = positive_float(ticker.get("last") or ticker.get("close") or ticker.get("ask") or ticker.get("bid"), "last price")
    quantity_plan = build_quantity_plan(client, trade_symbol, market, intent, last, adapter.contract_size(market))
    base_qty = None if is_all_quantity(intent) else quantity_plan["base_quantity"]
    order_amount = None if base_qty is None else quantity_plan["order_amount"]
    params = adapter.order_params(intent.action, intent.bbo)
    order_type = adapter.order_type(intent.bbo)
    price = None if order_type == "market" else adapter.maker_price(client, trade_symbol, side_for_action(intent.action), params)
    warnings = build_warnings(intent, resolution.canonical_symbol, quantity_plan, universe_path, last)
    if not adapter.supports_live():
        warnings.append({"code": "exchange_market_not_supported", "message": adapter.unsupported_reason()})
    if intent.quote_usdt is not None and quantity_plan["actual_quote"] > config.lab_max_quote_usdt:
        warnings.append({"code": "above_lab_safety_cap", "message": "planned notional is above local lab safety cap"})
    can_execute = not warnings and (intent.quote_usdt is None or float(intent.quote_usdt) <= config.lab_max_quote_usdt)
    preview = build_execution_preview(
        client,
        trade_symbol,
        market,
        resolution,
        intent,
        base_qty,
        order_amount,
        quantity_plan["actual_quote"],
        last,
        adapter=adapter,
        config=config,
        account_balance=(account_state or {}).get("balance"),
        account_positions=(account_state or {}).get("positions"),
    )
    usage = planning_usage or exchange_fetch_usage("cache_not_configured").to_mapping()
    return {
        "exchange": adapter.exchange,
        "market": intent.market,
        "bbo": intent.bbo,
        "action": intent.action,
        "symbol": trade_symbol,
        "canonical_symbol": resolution.canonical_symbol,
        "native_symbol": market.get("id") or resolution.native_symbol,
        "base_asset": adapter.base_asset(resolution, market),
        "quote_asset": adapter.quote_asset(resolution, market),
        "target_asset": adapter.base_asset(resolution, market) if intent.market == "spot" else None,
        "target_leverage": config.perp_target_leverage if intent.market == "perp" else None,
        "requested_quote_usdt": intent.quote_usdt,
        "last_price": last,
        "quantity": "ALL" if base_qty is None else format_decimal(base_qty),
        "quantity_step": format_decimal(quantity_plan["base_step"]),
        "quantity_unit": "contracts" if intent.market == "perp" and adapter.contract_size(market) != 1 else "base",
        "contract_size": adapter.contract_size(market) if intent.market == "perp" else None,
        "planned_delta_quantity": None if base_qty is None else format_decimal(base_qty),
        "order_amount": order_amount,
        "min_executable_quote_usdt": quantity_plan["min_executable_quote"],
        "min_executable_quantity": format_decimal(quantity_plan["min_executable_quantity"]),
        "planning_data_sources": usage,
        "can_execute": can_execute,
        "warnings": warnings,
        "blocked_reason": warnings[0]["message"] if warnings else None,
        "confirm_phrase": build_confirm_phrase(adapter.confirm_exchange(), intent, resolution, base_qty),
        "execution_preview": preview,
        "order": {
            "symbol": trade_symbol,
            "type": order_type,
            "side": side_for_action(intent.action),
            "amount": order_amount,
            "price": price,
            "params": params,
        },
    }


def canonical_symbol(exchange: str, market: str, symbol: str) -> str:
    return adapter_for(exchange, market).normalize_symbol(symbol).canonical_symbol


def ccxt_symbol(exchange: str, market: str, symbol: str) -> str:
    return adapter_for(exchange, market).normalize_symbol(symbol).ccxt_symbol


def build_warnings(
    intent: SingleLegIntent,
    canonical: str,
    quantity_plan: dict[str, Any],
    universe_path: str | Path | None,
    last: float,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if universe_path is not None:
        validation = validate_trading_symbol(canonical, intent.market, intent.exchange, universe_path)
        if not validation["supported"]:
            warnings.append({"code": "symbol_not_supported", "message": validation["reason"]})
    if intent.quote_usdt is not None and quantity_plan["below_minimum"]:
        warnings.append(
            {
                "code": "below_minimum_quantity_notional",
                "message": f"requested quote is below minimum executable quantity; min_executable_quote_usdt={quantity_plan['min_executable_quote']}",
            }
        )
    if last <= 0:
        warnings.append({"code": "price_unavailable", "message": "last price unavailable"})
    return warnings


def side_for_action(action: str) -> str:
    return {
        "buy": "buy",
        "sell": "sell",
        "open-long": "buy",
        "open-short": "sell",
        "close-long": "sell",
        "close-short": "buy",
    }[action]


def is_all_quantity(intent: SingleLegIntent) -> bool:
    if intent.market == "spot":
        return intent.action == "sell" and intent.quote_usdt is None
    return intent.action.startswith("close-") and intent.quote_usdt is None


def build_confirm_phrase(exchange: str, intent: SingleLegIntent, resolution: Any, quantity: float | None) -> str:
    action = intent.action.replace("-", "_").upper()
    if intent.quote_usdt is not None:
        qty = f"QUOTE_{format_decimal(float(intent.quote_usdt))}"
    else:
        qty = "ALL" if quantity is None else format_decimal(quantity)
    return f"LIVE_{exchange}_{intent.market.upper()}_{action}:{resolution.canonical_symbol.replace('/', '')}:{qty}"


def positive_float(value: Any, label: str) -> float:
    number = float(value or 0)
    if number <= 0:
        raise ValueError(f"{label} unavailable")
    return number
