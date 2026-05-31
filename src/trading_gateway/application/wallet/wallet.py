from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_gateway.domain.models import TransferIntent, WalletSnapshot, display_transfer_account, format_decimal
from trading_gateway.support.redaction import redact_mapping

_BALANCE_SYSTEM_KEYS = {"info", "timestamp", "datetime", "free", "used", "total", "debt"}
_BALANCE_IDENTITY_KEYS = {"asset", "ccy", "currency", "coin"}
_BALANCE_VALUE_KEYS = {
    "free",
    "locked",
    "total",
    "used",
    "eq",
    "availBal",
    "frozenBal",
    "balance",
    "availableBalance",
    "walletBalance",
    "marginBalance",
    "cashBalance",
    "equity",
    "available",
    "borrowed",
    "interest",
    "netAsset",
}
_POSITION_IDENTITY_KEYS = {"symbol", "instId", "contract"}
_POSITION_VALUE_KEYS = {
    "positionAmt",
    "pos",
    "holdVol",
    "size",
    "contracts",
    "notional",
    "notionalUsd",
    "value",
    "initialMargin",
    "unrealizedProfit",
    "unRealizedProfit",
}


def transfer_confirm_phrase(intent: TransferIntent) -> str:
    amount = format_decimal(float(intent.amount))
    return (
        f"LIVE_TRANSFER:{intent.exchange}:{intent.code}:{amount}:"
        f"{display_transfer_account(intent.from_account)}:{display_transfer_account(intent.to_account)}"
    )


def validate_transfer_request(intent: TransferIntent, *, live: bool, confirm: str) -> None:
    if not live:
        return
    expected = transfer_confirm_phrase(intent)
    if str(confirm or "").strip() != expected:
        raise ValueError(f"live transfer confirmation mismatch; expected {expected}")


def run_transfer(client: Any, intent: TransferIntent, *, live: bool, confirm: str) -> dict[str, Any]:
    expected = transfer_confirm_phrase(intent)
    validate_transfer_request(intent, live=live, confirm=confirm)
    if not live:
        return {"status": "dry_run", "transfer": intent.__dict__, "confirm": expected}
    result = client.transfer(intent.code, float(intent.amount), intent.from_account, intent.to_account)
    return redact_mapping({"status": "live", "transfer": result})


def fetch_wallet_snapshot(client: Any, exchange: str, symbol: str | None = None, *, nonzero_only: bool = True) -> WalletSnapshot:
    balances = client.fetch_balance()
    if nonzero_only:
        balances = filter_wallet_balances(balances)
    positions = []
    if hasattr(client, "fetch_positions"):
        positions = client.fetch_positions([symbol] if symbol else None) or []
    orders = []
    if symbol and hasattr(client, "fetch_open_orders"):
        orders = client.fetch_open_orders(symbol) or []
    return WalletSnapshot(
        exchange=exchange,
        balances=redact_mapping(balances),
        positions=redact_mapping(positions),
        open_orders=redact_mapping(orders),
    )


def filter_wallet_balances(balance: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(balance, dict):
        return balance
    filtered: dict[str, Any] = {}
    kept_codes: list[str] = []
    for key, value in balance.items():
        if key in _BALANCE_SYSTEM_KEYS:
            continue
        if isinstance(value, Mapping) and _looks_like_balance_row(value):
            if _row_has_nonzero(value, _BALANCE_VALUE_KEYS):
                kept_codes.append(str(key))
                filtered[key] = dict(value)
            continue
        filtered[key] = value
    for key in ("timestamp", "datetime"):
        if key in balance:
            filtered[key] = balance[key]
    if "info" in balance:
        filtered["info"] = _filter_raw_wallet_info(balance["info"])
    for key in ("free", "used", "total", "debt"):
        value = balance.get(key)
        if isinstance(value, Mapping):
            filtered[key] = {code: value[code] for code in kept_codes if code in value}
    return filtered


def _filter_raw_wallet_info(value: Any) -> Any:
    if isinstance(value, Mapping):
        if _looks_like_balance_row(value):
            return dict(value) if _row_has_nonzero(value, _BALANCE_VALUE_KEYS) else None
        if _looks_like_position_row(value):
            return dict(value) if _row_has_nonzero(value, _POSITION_VALUE_KEYS) else None
        return {
            key: filtered
            for key, item in value.items()
            for filtered in [_filter_raw_wallet_info(item)]
            if filtered is not None
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in (_filter_raw_wallet_info(entry) for entry in value) if item is not None]
    return value


def _looks_like_balance_row(value: Mapping[str, Any]) -> bool:
    keys = {str(key) for key in value.keys()}
    return bool(keys & _BALANCE_VALUE_KEYS) and (bool(keys & _BALANCE_IDENTITY_KEYS) or {"free", "used", "total"} <= keys)


def _looks_like_position_row(value: Mapping[str, Any]) -> bool:
    keys = {str(key) for key in value.keys()}
    return bool(keys & _POSITION_IDENTITY_KEYS) and bool(keys & _POSITION_VALUE_KEYS)


def _row_has_nonzero(value: Mapping[str, Any], keys: set[str]) -> bool:
    return any(_nonzero(value.get(key)) for key in keys if key in value)


def _nonzero(value: Any) -> bool:
    try:
        return Decimal(str(value or "0")) != 0
    except (InvalidOperation, ValueError):
        return False
