from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_gateway.application.wallet.summary import summarize_market


def fetch_fast_summary_market(client: Any, exchange: str, market: str, *, include_positions: bool) -> dict[str, Any]:
    if exchange == "binance":
        return _binance(client, market, include_positions)
    if exchange == "okx":
        return _okx(client, market, include_positions)
    if exchange == "gate":
        return _gate(client, market, include_positions)
    if exchange == "mexc":
        return _mexc(client, market, include_positions)
    raise ValueError(f"unsupported fast wallet summary exchange: {exchange}")


def _binance(client: Any, market: str, include_positions: bool) -> dict[str, Any]:
    if market == "spot":
        raw = client.privateGetAccount({"omitZeroBalances": "true"})
        row = _find(raw.get("balances"), "asset", "USDT")
        free = row.get("free") if row else None
        locked = row.get("locked") if row else None
        return summarize_market("binance", market, _ccxt_balance(_add(free, locked), free, locked))
    if not include_positions:
        row = _find(client.fapiPrivateV2GetBalance(), "asset", "USDT")
        return summarize_market("binance", market, _ccxt_balance(row.get("balance"), row.get("availableBalance"), None))
    raw = client.fapiPrivateV3GetAccount()
    positions = _positions(raw.get("positions"), "positionAmt") if include_positions else None
    return summarize_market(
        "binance",
        market,
        _ccxt_balance(raw.get("totalWalletBalance"), raw.get("availableBalance"), None),
        positions,
    )


def _okx(client: Any, market: str, include_positions: bool) -> dict[str, Any]:
    balance = _client_cache(client, "_tg_okx_usdt_balance", lambda: client.privateGetAccountBalance({"ccy": "USDT"}))
    positions = None
    if market == "swap" and include_positions:
        positions = _positions(client.privateGetAccountPositions().get("data"), "pos")
    return summarize_market("okx", market, {"info": balance}, positions)


def _gate(client: Any, market: str, include_positions: bool) -> dict[str, Any]:
    if market == "spot":
        try:
            with _temporary_timeout(client, 2000):
                rows = client.privateSpotGetAccounts({"currency": "USDT"})
            row = rows[0] if rows else {}
            total = _add(row.get("available"), row.get("locked"))
            free = row.get("available")
            locked = row.get("locked")
        except Exception:
            row = _gate_total_detail(client, "spot")
            total = row.get("amount")
            free = row.get("amount")
            locked = None
        return summarize_market(
            "gate",
            market,
            _ccxt_balance(total, free, locked),
        )
    raw = client.privateFuturesGetSettleAccounts({"settle": "usdt"})
    positions = _positions(client.privateFuturesGetSettlePositions({"settle": "usdt"}), "size") if include_positions else None
    return summarize_market("gate", market, _ccxt_balance(raw.get("total"), raw.get("available"), None), positions)


def _mexc(client: Any, market: str, include_positions: bool) -> dict[str, Any]:
    if market == "spot":
        raw = client.spotPrivateGetAccount()
        row = _find(raw.get("balances"), "asset", "USDT")
        return summarize_market("mexc", market, _ccxt_balance(_add(row.get("free"), row.get("locked")), row.get("free"), row.get("locked")))
    raw = client.contractPrivateGetAccountAssets()
    row = _find(raw.get("data"), "currency", "USDT")
    positions = _positions(client.contractPrivateGetPositionOpenPositions().get("data"), "holdVol") if include_positions else None
    return summarize_market(
        "mexc",
        market,
        _ccxt_balance(_first(row.get("cashBalance"), row.get("equity")), row.get("availableBalance"), row.get("frozenBalance")),
        positions,
    )


def _ccxt_balance(total: Any, free: Any, used: Any) -> dict[str, Any]:
    return {"total": {"USDT": total}, "free": {"USDT": free}, "used": {"USDT": used}}


def _gate_total_detail(client: Any, account: str) -> dict[str, Any]:
    raw = _client_cache(client, "_tg_gate_total_balance", client.privateWalletGetTotalBalance)
    details = raw.get("details") if isinstance(raw, dict) else {}
    row = details.get(account) if isinstance(details, dict) else {}
    return row if isinstance(row, dict) else {}


def _client_cache(client: Any, key: str, factory: Any) -> Any:
    if not hasattr(client, key):
        setattr(client, key, factory())
    return getattr(client, key)


@contextmanager
def _temporary_timeout(client: Any, timeout_ms: int):
    old_timeout = getattr(client, "timeout", None)
    client.timeout = timeout_ms
    try:
        yield
    finally:
        client.timeout = old_timeout


def _find(rows: Any, key: str, value: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and str(row.get(key) or "").upper() == value:
            return row
    return {}


def _positions(rows: Any, amount_key: str) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    return [{"contracts": "1"} for row in rows if isinstance(row, dict) and _nonzero(row.get(amount_key))]


def _add(left: Any, right: Any) -> str:
    return _decimal_text(_decimal(left) + _decimal(right))


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _nonzero(value: Any) -> bool:
    return _decimal(value) != 0


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
