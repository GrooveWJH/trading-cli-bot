from __future__ import annotations

from typing import Any

from trading_gateway.adapters.exchanges.positions import position_quantity
from trading_gateway.domain.models import format_decimal
from trading_gateway.support.tolerance import clamp_quantity_to_zero

from .intent import SingleLegIntent
from .quantity import clean_number


def build_execution_preview(
    client: Any,
    symbol: str,
    market: dict[str, Any],
    resolution: Any,
    intent: SingleLegIntent,
    base_quantity: float | None,
    order_amount: float | None,
    estimated_quote: float,
    last_price: float,
    *,
    adapter: Any,
    config: Any,
    account_balance: dict[str, Any] | None = None,
    account_positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    preview = {
        "symbol": symbol,
        "canonical_symbol": resolution.canonical_symbol,
        "native_symbol": market.get("id") or resolution.native_symbol,
        "planned_delta_quantity": "ALL" if base_quantity is None else format_decimal(base_quantity),
        "order_amount": order_amount,
        "estimated_quote_usdt": estimated_quote,
        "submit_order": True,
    }
    if intent.market == "spot":
        base_asset = str(market.get("base") or resolution.canonical_symbol.split("/")[0]).upper()
        quote_asset = str(market.get("quote") or resolution.canonical_symbol.split("/")[1]).upper()
        balance = safe_balance(client, base_asset, quote_asset, payload=account_balance)
        fallback = amount_step_value(market)
        current = clamp_quantity_to_zero(
            balance["base_total"],
            price=last_price,
            tolerance_quote_usdt=config.spot_execution.target_tolerance_quote_usdt,
            fallback_quantity=fallback,
        )
        target = spot_target_quantity(intent.action, current, base_quantity)
        return {
            **preview,
            "kind": "spot_target_preview",
            "asset": base_asset,
            "current_quantity": current,
            "target_quantity": target,
            "remaining_quantity": preview_remaining(base_quantity, current, target),
            "current_quote_free": balance["quote_free"],
        }
    contract_size = float(market.get("contractSize") or 1.0)
    fallback = amount_step_value(market) * (contract_size if contract_size > 0 else 1.0)
    current = clamp_quantity_to_zero(
        perp_current_quantity(client, symbol, intent.action, positions=account_positions),
        price=last_price,
        tolerance_quote_usdt=config.perp_execution.target_tolerance_quote_usdt,
        fallback_quantity=fallback,
    )
    target = perp_target_quantity(intent.action, current, base_quantity)
    return {
        **preview,
        "kind": "perp_target_preview",
        "position_side": "long" if intent.action.endswith("long") else "short",
        "current_quantity": current,
        "target_quantity": target,
        "remaining_quantity": preview_remaining(base_quantity, current, target),
    }


def safe_balance(client: Any, base_asset: str, quote_asset: str, *, payload: dict[str, Any] | None = None) -> dict[str, float | None]:
    if payload is None and not hasattr(client, "fetch_balance"):
        return {"base_total": None, "quote_free": None}
    try:
        source = payload if payload is not None else client.fetch_balance() or {}
    except Exception:  # noqa: BLE001
        return {"base_total": None, "quote_free": None}
    return {
        "base_total": balance_value(source, base_asset, "total"),
        "quote_free": balance_value(source, quote_asset, "free"),
    }


def balance_value(payload: dict[str, Any], asset: str, key: str) -> float | None:
    raw_row = payload.get(asset)
    row = raw_row if isinstance(raw_row, dict) else {}
    value = row.get(key)
    raw_bucket = payload.get(key)
    if value is None and isinstance(raw_bucket, dict):
        value = raw_bucket.get(asset)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def spot_target_quantity(action: str, current: float | None, base_quantity: float | None) -> float | None:
    if current is None:
        return None
    if base_quantity is None:
        return 0.0 if action == "sell" else current
    if action == "buy":
        return clean_number(current + base_quantity)
    return clean_number(max(0.0, current - base_quantity))


def perp_current_quantity(client: Any, symbol: str, action: str, *, positions: list[dict[str, Any]] | None = None) -> float | None:
    if positions is None and not hasattr(client, "fetch_positions"):
        return None
    try:
        payload = positions if positions is not None else client.fetch_positions([symbol]) or []
    except Exception:  # noqa: BLE001
        return None
    side = "long" if action.endswith("long") else "short"
    return position_quantity(payload, symbol, side, hedge_mode(client))


def perp_target_quantity(action: str, current: float | None, base_quantity: float | None) -> float | None:
    if current is None:
        return None
    if base_quantity is None:
        return 0.0 if action.startswith("close-") else current
    if action.startswith("open-"):
        return clean_number(current + base_quantity)
    return clean_number(max(0.0, current - base_quantity))


def hedge_mode(client: Any) -> bool:
    method = getattr(client, "fapiPrivateGetPositionSideDual", None) or getattr(client, "fapiprivate_get_positionside_dual", None)
    if not callable(method):
        return False
    try:
        value = (method() or {}).get("dualSidePosition")
    except Exception:  # noqa: BLE001
        return False
    return value is True or str(value).lower() == "true"


def preview_remaining(base_quantity: float | None, current: float | None, target: float | None) -> str:
    if base_quantity is None:
        return "ALL"
    if current is None or target is None:
        return format_decimal(base_quantity)
    return format_decimal(abs(target - current))


def amount_step_value(market: dict[str, Any]) -> float:
    precision = (market.get("precision") or {}).get("amount")
    if isinstance(precision, int):
        return 10 ** (-precision)
    if isinstance(precision, float) and precision > 0:
        return precision if precision <= 1 else 10 ** (-int(precision))
    return 0.0
