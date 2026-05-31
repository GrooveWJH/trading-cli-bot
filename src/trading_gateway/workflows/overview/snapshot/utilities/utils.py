from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from trading_gateway.workflows.overview.snapshot.model.models import AssetBalance


def asset_balance(
    asset: Any,
    total: Any,
    free: Any,
    locked: Any,
    *,
    source_account: str,
    borrowed: Any = "0",
    interest: Any = "0",
    usdt_value: Any = None,
    status: str = "ok",
) -> AssetBalance:
    return AssetBalance(
        asset=str(asset or "").upper(),
        total=num(total),
        free=num(free),
        locked=num(locked),
        borrowed=num(borrowed),
        interest=num(interest),
        usdt_value=None if usdt_value in (None, "") else num(usdt_value),
        source_account=source_account,
        status=status,
    )


def num(value: Any) -> str:
    dec = decimal(value)
    abs_dec = abs(dec)
    if abs_dec >= Decimal("1000"):
        dec = dec.quantize(Decimal("0.01"))
    elif abs_dec >= Decimal("1"):
        dec = dec.quantize(Decimal("0.000001"))
    elif abs_dec != 0:
        dec = dec.quantize(Decimal("0.0000000001"))
    text = format(dec.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def add(left: Any, right: Any) -> str:
    return num(decimal(left) + decimal(right))


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def nonzero(value: Any) -> bool:
    return decimal(value) != 0


def first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def side_from_amount(value: Any) -> str:
    amount = decimal(value)
    return "long" if amount > 0 else "short" if amount < 0 else "flat"


def signed_size(amount: Any, side: str) -> str:
    dec = abs(decimal(amount))
    return num(-dec if side == "short" else dec)
