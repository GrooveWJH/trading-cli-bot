from __future__ import annotations


def quantity_tolerance_from_quote(price: float | None, tolerance_quote_usdt: float, fallback_quantity: float = 0.0) -> float:
    if price is None or price <= 0 or tolerance_quote_usdt <= 0:
        return max(0.0, fallback_quantity)
    return max(0.0, tolerance_quote_usdt / price)


def residual_quote_usdt(quantity: float | None, price: float | None) -> float:
    if quantity is None or price is None or price <= 0:
        return 0.0
    return float(f"{abs(quantity) * price:.12g}")


def clamp_quantity_to_zero(
    quantity: float | None,
    *,
    price: float | None,
    tolerance_quote_usdt: float,
    fallback_quantity: float = 0.0,
) -> float | None:
    if quantity is None:
        return None
    tolerance = quantity_tolerance_from_quote(price, tolerance_quote_usdt, fallback_quantity)
    return 0.0 if abs(quantity) <= tolerance else quantity
