from __future__ import annotations

from typing import Any

from trading_gateway.app.config import get_gateway_config


def order_fee_summary(plan: Any, order: dict[str, Any] | None, status: dict[str, Any] | None = None, *, market: str | None = None, amount: float | None = None, price: float | None = None, liquidity: str | None = None) -> dict[str, Any]:
    plan_map = plan.raw if hasattr(plan, "raw") else plan
    order = order or {}
    status = status or {}
    market = market or str(plan_map.get("market") or ("spot" if ":USDT" not in str(order.get("symbol", "")) else "perp"))
    liquidity = liquidity or ("taker" if str(order.get("type") or "").lower() == "market" else "maker")
    actual = _actual_fee(status) or _actual_fee(order)
    notional = _notional(plan_map, order, status, amount, price)
    if actual:
        rate_bps = actual.get("rate_bps") or (actual["cost"] / notional * 10000 if notional and notional > 0 else None)
        return {**actual, "source": "actual", "rate_bps": rate_bps, "notional_usdt": notional, "liquidity": liquidity}
    rate_bps = get_gateway_config().fee_bps(market, liquidity, _exchange(plan_map, market))
    return {
        "source": "estimated",
        "cost": None if notional is None else notional * rate_bps / 10000,
        "currency": _quote_asset(plan_map),
        "rate_bps": rate_bps,
        "notional_usdt": notional,
        "liquidity": liquidity,
    }


def fee_report(plan: Any, steps: list[dict[str, Any]]) -> dict[str, Any]:
    fees = [row["fee"] for row in steps if _has_fee_signal(row.get("fee"))]
    if not fees:
        return {"source": "none", "items": [], "total_by_currency": {}}
    totals: dict[str, float] = {}
    for fee in fees:
        if fee.get("cost") is None:
            continue
        currency = str(fee.get("currency") or _quote_asset(plan.raw if hasattr(plan, "raw") else plan))
        totals[currency] = totals.get(currency, 0.0) + float(fee.get("cost") or 0)
    source = "actual" if any(fee.get("source") == "actual" for fee in fees) else "estimated"
    return {"source": source, "items": fees, "total_by_currency": totals}


def _has_fee_signal(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("cost") is not None:
        return float(value.get("cost") or 0) > 0
    return value.get("rate_bps") is not None or value.get("source") in {"actual", "estimated"}


def _actual_fee(row: dict[str, Any]) -> dict[str, Any] | None:
    fee = row.get("fee") if isinstance(row.get("fee"), dict) else None
    if fee and fee.get("cost") is not None:
        return {"cost": float(fee["cost"]), "currency": str(fee.get("currency") or "USDT"), "rate_bps": _rate_bps(fee.get("rate"))}
    raw_fees = row.get("fees")
    fees: list[Any] = raw_fees if isinstance(raw_fees, list) else []
    costs = [item for item in fees if isinstance(item, dict) and item.get("cost") is not None]
    if not costs:
        return None
    currency = str(costs[0].get("currency") or "USDT")
    return {"cost": sum(float(item["cost"]) for item in costs if str(item.get("currency") or currency) == currency), "currency": currency, "rate_bps": _rate_bps(costs[0].get("rate"))}


def _notional(plan: dict[str, Any], order: dict[str, Any], status: dict[str, Any], amount: float | None, price: float | None) -> float | None:
    filled = _filled_amount(order, status, amount)
    if filled is None:
        return None
    avg = _first_float(status, "average", "avgPrice", "price") or _first_float(status.get("info") or {}, "avgPrice", "price")
    px = avg or price or _first_float(order, "average", "price") or _first_float(plan, "last_price", "reference_price") or 0
    return abs(_base_amount(plan, filled) * px)


def _filled_amount(order: dict[str, Any], status: dict[str, Any], amount: float | None) -> float | None:
    filled = _first_float(status, "filled")
    if filled is not None:
        return filled
    if status and status.get("status") != "closed":
        return 0.0
    fallback = _first_float(order, "filled", "amount")
    if fallback is not None:
        return fallback
    return None if amount is None else float(amount)


def _base_amount(plan: dict[str, Any], amount: float) -> float:
    if plan.get("quantity_unit") == "contracts":
        return amount * float(plan.get("contract_size") or 1)
    return amount


def _first_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = float(row.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return None


def _rate_bps(value: Any) -> float | None:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate * 10000


def _quote_asset(plan: dict[str, Any]) -> str:
    return str(plan.get("quote_asset") or "USDT").upper()


def _exchange(plan: dict[str, Any], market: str) -> str | None:
    if market == "spot":
        return plan.get("spot_exchange") or plan.get("exchange")
    if market in {"perp", "swap"}:
        return plan.get("perp_exchange") or plan.get("exchange")
    return plan.get("exchange")
