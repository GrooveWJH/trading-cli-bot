from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_gateway.adapters.exchanges.rules import amount_step
from trading_gateway.app.config import get_gateway_config
from trading_gateway.domain.models import format_decimal
from trading_gateway.support.redaction import redact_mapping
from trading_gateway.workflows.overview.planning_account_state import exchange_fetch_usage

from .helpers import (
    book_top,
    common_quantity,
    confirm_phrase,
    hedge_mode,
    market_for,
    minimums_for_pair,
    pair_adapter,
    perp_quote_free,
    position_short_quantity,
    reference_price,
    spot_balances,
    warnings_for_pair,
)


def build_pair_plan(
    spot_client: Any,
    perp_client: Any,
    *,
    spot_exchange: str,
    perp_exchange: str,
    symbol: str,
    quote_usdt: float,
    universe_path: str | Path | None = None,
    account_state: dict[str, Any] | None = None,
    planning_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if quote_usdt <= 0:
        raise ValueError("quote_usdt must be positive")
    config = get_gateway_config()
    spot_adapter = pair_adapter(spot_exchange, "spot")
    perp_adapter = pair_adapter(perp_exchange, "perp")
    spot_resolution = spot_adapter.normalize_symbol(symbol)
    perp_resolution = perp_adapter.normalize_symbol(symbol)
    spot_market = market_for(spot_adapter, spot_client, spot_resolution)
    perp_market = market_for(perp_adapter, perp_client, perp_resolution)
    perp_contract_size = perp_adapter.contract_size(perp_market)
    canonical_symbol = spot_resolution.canonical_symbol
    spot_symbol = str(spot_market.get("symbol") or spot_resolution.ccxt_symbol)
    perp_symbol = str(perp_market.get("symbol") or perp_resolution.ccxt_symbol)
    spot_book = book_top(spot_client, spot_symbol)
    perp_ref = reference_price(perp_client, perp_symbol)
    reference_price_value = max(spot_book["ask"], perp_ref)
    target_qty = common_quantity(
        spot_client,
        perp_client,
        spot_symbol,
        perp_symbol,
        spot_market,
        perp_market,
        quote_usdt,
        reference_price_value,
        perp_contract_size,
    )
    minimums = minimums_for_pair(
        spot_client=spot_client,
        perp_client=perp_client,
        spot_symbol=spot_symbol,
        perp_symbol=perp_symbol,
        spot_market=spot_market,
        perp_market=perp_market,
        reference_price_value=reference_price_value,
        quote_usdt=quote_usdt,
        perp_contract_size=perp_contract_size,
    )
    min_qty = max(float(minimums["spot"]["min_quantity"]), float(minimums["perp"]["min_quantity"]))
    min_quote = max(float(minimums["spot"]["min_quote_usdt"]), float(minimums["perp"]["min_quote_usdt"]))
    warnings = warnings_for_pair(
        spot_exchange=spot_exchange,
        perp_exchange=perp_exchange,
        canonical_symbol=canonical_symbol,
        quantity=target_qty,
        min_quantity=min_qty,
        quote_usdt=quote_usdt,
        min_quote=min_quote,
        effective_source=str(minimums["effective_source"]),
        universe_path=universe_path,
        max_quote=config.lab_max_quote_usdt,
        spot_adapter=spot_adapter,
        perp_adapter=perp_adapter,
    )
    usage = planning_usage or exchange_fetch_usage("cache_not_configured").to_mapping()
    spot_balance = spot_balances(
        spot_client,
        spot_adapter.base_asset(spot_resolution, spot_market),
        spot_adapter.quote_asset(spot_resolution, spot_market),
        payload=(account_state or {}).get("spot_balance"),
    )
    current_short = position_short_quantity(
        perp_client,
        perp_symbol,
        hedge_mode(perp_client),
        positions=(account_state or {}).get("perp_positions"),
    )
    target_spot = spot_balance["base_total"] + target_qty
    target_short = current_short + target_qty
    estimated_spot_quote = target_qty * spot_book["ask"]
    perp_quote_available = perp_quote_free(
        perp_client,
        perp_adapter.quote_asset(perp_resolution, perp_market),
        payload=(account_state or {}).get("perp_balance"),
    )
    if spot_balance["quote_free"] < estimated_spot_quote:
        warnings.append({"code": "insufficient_spot_quote_balance", "message": "spot quote balance is below estimated buy cost"})
    if perp_quote_available < target_qty * perp_ref:
        warnings.append({"code": "insufficient_perp_margin", "message": "perp quote available balance is below conservative notional check"})
    can_execute = not warnings
    return redact_mapping(
        {
            "mode": "pair_trading_plan",
            "intent": "open",
            "spot_exchange": spot_adapter.exchange,
            "perp_exchange": perp_adapter.exchange,
            "canonical_symbol": canonical_symbol,
            "symbol": spot_symbol,
            "perp_symbol": perp_symbol,
            "spot_native_symbol": spot_market.get("id") or spot_resolution.native_symbol,
            "perp_native_symbol": perp_market.get("id") or perp_resolution.native_symbol,
            "base_asset": spot_adapter.base_asset(spot_resolution, spot_market),
            "quote_asset": spot_adapter.quote_asset(spot_resolution, spot_market),
            "perp_contract_size": perp_contract_size,
            "requested_quote_usdt": quote_usdt,
            "reference_price": reference_price_value,
            "perp_target_leverage": config.perp_execution.target_leverage,
            "target_delta_quantity": format_decimal(target_qty),
            "quantity_step": format_decimal(max(amount_step(spot_market), amount_step(perp_market) * perp_adapter.contract_size(perp_market))),
            "min_executable_quote_usdt": min_quote,
            "minimums": minimums,
            "planning_data_sources": usage,
            "can_execute": can_execute,
            "warnings": warnings,
            "blocked_reason": warnings[0]["message"] if warnings else None,
            "confirm_phrase": confirm_phrase(spot_adapter.exchange, perp_adapter.exchange, canonical_symbol, quote_usdt),
            "spot": {
                "current_quantity": spot_balance["base_total"],
                "target_quantity": target_spot,
                "estimated_quote_usdt": estimated_spot_quote,
                "best_bid": spot_book["bid"],
                "best_ask": spot_book["ask"],
            },
            "perp": {
                "current_short_quantity": current_short,
                "target_short_quantity": target_short,
                "estimated_notional_usdt": target_qty * perp_ref,
            },
            "execution_preview": {
                "kind": "pair_target_preview",
                "spot_order": {"side": "buy", "type": "limit_maker" if spot_adapter.exchange == "binance" else "limit", "price": spot_book["bid"], "amount": target_qty},
                "perp_order": {"side": "sell", "type": config.bbo_order_type, "price": perp_ref, "amount": target_qty},
                "target_delta_quantity": format_decimal(target_qty),
                "spot_current_quantity": spot_balance["base_total"],
                "spot_target_quantity": target_spot,
                "perp_short_current_quantity": current_short,
                "perp_short_target_quantity": target_short,
            },
        }
    )
