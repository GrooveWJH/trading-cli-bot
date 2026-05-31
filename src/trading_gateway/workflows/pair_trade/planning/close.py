from __future__ import annotations

from pathlib import Path
from typing import Any

from trading_gateway.adapters.exchanges.rules import amount_step
from trading_gateway.app.config import get_gateway_config
from trading_gateway.domain.models import format_decimal
from trading_gateway.domain.route_universe import validate_trading_symbol
from trading_gateway.support.redaction import redact_mapping
from trading_gateway.workflows.overview.planning_account_state import exchange_fetch_usage

from .helpers import (
    book_top,
    close_confirm_phrase,
    hedge_mode,
    market_for,
    pair_adapter,
    position_short_quantity,
    reference_price,
    spot_balances,
)


def build_pair_close_plan(
    spot_client: Any,
    perp_client: Any,
    *,
    spot_exchange: str,
    perp_exchange: str,
    symbol: str,
    universe_path: str | Path | None = None,
    account_state: dict[str, Any] | None = None,
    planning_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    target_qty = max(spot_balance["base_total"], current_short)
    warnings = close_warnings(
        universe_path=universe_path,
        canonical_symbol=canonical_symbol,
        spot_exchange=spot_exchange,
        perp_exchange=perp_exchange,
        spot_adapter=spot_adapter,
        perp_adapter=perp_adapter,
        spot_quantity=spot_balance["base_total"],
        perp_quantity=current_short,
        target_qty=target_qty,
    )
    can_execute = not any(row["code"] in BLOCKING_CLOSE_WARNINGS for row in warnings)
    spot_target = max(0.0, spot_balance["base_total"] - target_qty)
    perp_target = max(0.0, current_short - target_qty)
    return redact_mapping(
        {
            "mode": "pair_close_plan",
            "intent": "close",
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
            "requested_quote_usdt": None,
            "reference_price": max(spot_book["bid"], perp_ref),
            "perp_target_leverage": config.perp_execution.target_leverage,
            "target_delta_quantity": format_decimal(target_qty),
            "quantity_step": format_decimal(max(amount_step(spot_market), amount_step(perp_market) * perp_contract_size)),
            "min_executable_quote_usdt": 0.0,
            "planning_data_sources": usage,
            "can_execute": can_execute,
            "warnings": warnings,
            "blocked_reason": next((row["message"] for row in warnings if row["code"] in BLOCKING_CLOSE_WARNINGS), None),
            "confirm_phrase": close_confirm_phrase(spot_adapter.exchange, perp_adapter.exchange, canonical_symbol),
            "spot": {
                "current_quantity": spot_balance["base_total"],
                "target_quantity": spot_target,
                "estimated_quote_usdt": target_qty * spot_book["bid"],
                "best_bid": spot_book["bid"],
                "best_ask": spot_book["ask"],
            },
            "perp": {
                "current_short_quantity": current_short,
                "target_short_quantity": perp_target,
                "estimated_notional_usdt": target_qty * perp_ref,
            },
            "execution_preview": {
                "kind": "pair_close_preview",
                "spot_order": {"side": "sell", "type": "limit_maker" if spot_adapter.exchange == "binance" else "limit", "price": spot_book["ask"], "amount": target_qty},
                "perp_order": {"side": "buy", "type": config.bbo_order_type, "price": perp_ref, "amount": target_qty},
                "target_delta_quantity": format_decimal(target_qty),
                "spot_current_quantity": spot_balance["base_total"],
                "spot_target_quantity": spot_target,
                "perp_short_current_quantity": current_short,
                "perp_short_target_quantity": perp_target,
            },
        }
    )


BLOCKING_CLOSE_WARNINGS = {"symbol_not_supported", "exchange_market_not_supported", "pair_close_nothing_to_close"}


def close_warnings(
    *,
    universe_path: str | Path | None,
    canonical_symbol: str,
    spot_exchange: str,
    perp_exchange: str,
    spot_adapter: Any,
    perp_adapter: Any,
    spot_quantity: float,
    perp_quantity: float,
    target_qty: float,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if universe_path is not None:
        for exchange, market in ((spot_exchange, "spot"), (perp_exchange, "perp")):
            result = validate_trading_symbol(canonical_symbol, market, exchange, universe_path)
            if not result["supported"]:
                warnings.append({"code": "symbol_not_supported", "message": result["reason"]})
    for adapter in (spot_adapter, perp_adapter):
        if not adapter.supports_live():
            warnings.append({"code": "exchange_market_not_supported", "message": adapter.unsupported_reason()})
    if target_qty <= 0:
        warnings.append({"code": "pair_close_nothing_to_close", "message": "no spot inventory or perp short exposure is available to close"})
    elif abs(spot_quantity - perp_quantity) > 0:
        warnings.append({"code": "pair_close_residual_cleanup_required", "message": "spot and perp quantities are mismatched; close workflow will continue into residual cleanup if needed"})
    return warnings
