from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from trading_gateway.domain.models import PUBLIC_MARKET_TYPES, SUPPORTED_EXCHANGES, display_market
from trading_gateway.support.redaction import redact_mapping


def summarize_market(
    exchange: str,
    market: str,
    balances: dict[str, Any] | None,
    positions: list[dict[str, Any]] | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    if error:
        return _market_row(exchange, market, error=error)
    balance = redact_mapping(balances or {})
    assets = _extract_assets(balance)
    return _market_row(
        exchange,
        market,
        account=_account_kind(exchange, balance),
        assets=assets,
        equity_usdt=_first_text(_raw_equity_usdt(balance), _asset_field(assets, "USDT", "total")),
        available_usdt=_first_text(_raw_available_usdt(balance), _asset_field(assets, "USDT", "free")),
        positions_count=_active_positions_count(positions or []),
    )


def build_summary_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "exchanges": []}
    by_exchange: dict[str, dict[str, Any]] = {name: {"exchange": name, "markets": {}} for name in SUPPORTED_EXCHANGES}
    for row in rows:
        by_exchange.setdefault(row["exchange"], {"exchange": row["exchange"], "markets": {}})
        by_exchange[row["exchange"]]["markets"][row["market"]] = row
    payload["exchanges"] = [entry for entry in by_exchange.values() if entry["markets"]]
    return payload


def format_summary_table(payload: dict[str, Any]) -> str:
    elapsed = f" query_ms={payload['query_ms']}" if isinstance(payload.get("query_ms"), int) else ""
    cache = f" cache=hit age_ms={payload['cache_age_ms']}" if payload.get("cache_hit") else ""
    lines = [
        f"Wallet summary: USDT balances only; no credentials or raw private payloads are printed.{elapsed}{cache}",
        "EXCHANGE ACCOUNT  MARKET   USDT_BALANCE                     EQUITY_USDT  AVAILABLE_USDT  POSITIONS  QUERY_MS  STATUS",
    ]
    for exchange in payload.get("exchanges", []):
        for row in _display_rows(exchange):
            lines.append(_format_row(row))
    return "\n".join(lines)


def _display_rows(exchange: dict[str, Any]) -> list[dict[str, Any]]:
    markets = exchange.get("markets", {})
    rows = [markets[name] for name in PUBLIC_MARKET_TYPES if name in markets]
    if len(rows) == 2 and rows[0].get("account") == "unified" and _same_balance(rows[0], rows[1]):
        merged = dict(rows[0])
        merged["market"] = "unified"
        counts = [row.get("positions_count") for row in rows]
        merged["positions_count"] = None if any(value is None for value in counts) else max(int(value or 0) for value in counts)
        merged["query_ms"] = max(int(row.get("query_ms") or 0) for row in rows)
        return [merged]
    return rows


def _format_row(row: dict[str, Any]) -> str:
    status = row.get("error") or "ok"
    balances = _assets_text(row.get("assets") or [])
    return (
        f"{row['exchange']:<8} {str(row.get('account') or '-'):<8} "
        f"{display_market(row['market']):<8} "
        f"{balances:<32.32} "
        f"{_dash(row.get('equity_usdt')):<12} "
        f"{_dash(row.get('available_usdt')):<15} "
        f"{_int_text(row, 'positions_count'):<9} "
        f"{_int_text(row, 'query_ms'):<8} "
        f"{status}"
    )


def _market_row(
    exchange: str,
    market: str,
    *,
    account: str = "separate",
    assets: list[dict[str, str]] | None = None,
    equity_usdt: str | None = None,
    available_usdt: str | None = None,
    positions_count: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "exchange": exchange,
        "market": display_market(market),
        "account": account,
        "assets": assets or [],
        "equity_usdt": equity_usdt,
        "available_usdt": available_usdt,
        "positions_count": positions_count,
        "error": error,
    }


def _extract_assets(balance: dict[str, Any]) -> list[dict[str, str]]:
    raw_assets = _okx_assets(balance) or _ccxt_assets(balance)
    return [item for item in sorted(raw_assets, key=lambda item: item["asset"]) if item["asset"] == "USDT"]


def _ccxt_assets(balance: dict[str, Any]) -> list[dict[str, str]]:
    totals = _dict_field(balance, "total")
    frees = _dict_field(balance, "free")
    used = _dict_field(balance, "used")
    codes = set(totals) | set(frees) | set(used)
    for code, row in balance.items():
        if isinstance(row, dict) and any(key in row for key in ("total", "free", "used")):
            codes.add(str(code))
    assets = []
    for code in sorted(codes):
        asset = str(code)
        row = _dict_field(balance, asset)
        item = _asset_row(asset, totals.get(asset, row.get("total")), frees.get(asset, row.get("free")), used.get(asset, row.get("used")))
        if _asset_nonzero(item):
            assets.append(item)
    return assets


def _okx_assets(balance: dict[str, Any]) -> list[dict[str, str]]:
    details = _okx_details(balance)
    assets = []
    for row in details:
        code = str(row.get("ccy") or "").upper()
        item = _asset_row(code, row.get("eq"), row.get("availBal"), row.get("frozenBal"))
        if code and _asset_nonzero(item):
            assets.append(item)
    return assets


def _asset_row(code: str, total: Any, free: Any, used: Any) -> dict[str, str]:
    return {"asset": str(code).upper(), "total": _num_text(total), "free": _num_text(free), "used": _num_text(used)}


def _asset_nonzero(item: dict[str, str]) -> bool:
    if item.get("total") != "":
        return _nonzero(item.get("total")) or _nonzero(item.get("used"))
    return _nonzero(item.get("free")) or _nonzero(item.get("used"))


def _active_positions_count(positions: list[dict[str, Any]]) -> int:
    keys = ("contracts", "contractSize", "notional", "initialMargin", "unrealizedPnl")
    return sum(1 for row in positions if any(_nonzero(row.get(key)) for key in keys))


def _raw_equity_usdt(balance: dict[str, Any]) -> str | None:
    info = _dict_field(balance, "info")
    return _first_text(info.get("totalWalletBalance"), info.get("totalMarginBalance"), _okx_total_eq(balance))


def _raw_available_usdt(balance: dict[str, Any]) -> str | None:
    info = _dict_field(balance, "info")
    return _first_text(info.get("availableBalance"), info.get("maxWithdrawAmount"), _okx_usdt_detail(balance, "availBal"))


def _okx_total_eq(balance: dict[str, Any]) -> Any:
    data = _okx_data(balance)
    return data[0].get("totalEq") if data else None


def _okx_usdt_detail(balance: dict[str, Any], field: str) -> Any:
    for row in _okx_details(balance):
        if str(row.get("ccy") or "").upper() == "USDT":
            return row.get(field)
    return None


def _okx_details(balance: dict[str, Any]) -> list[dict[str, Any]]:
    data = _okx_data(balance)
    details = data[0].get("details") if data else []
    return details if isinstance(details, list) else []


def _okx_data(balance: dict[str, Any]) -> list[dict[str, Any]]:
    info = _dict_field(balance, "info")
    data = info.get("data")
    return data if isinstance(data, list) and data and isinstance(data[0], dict) else []


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return payload[key] if isinstance(payload.get(key), dict) else {}


def _account_kind(exchange: str, balance: dict[str, Any]) -> str:
    return "unified" if exchange == "okx" and _okx_details(balance) else "separate"


def _same_balance(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("assets") == right.get("assets")
        and left.get("equity_usdt") == right.get("equity_usdt")
        and left.get("available_usdt") == right.get("available_usdt")
        and not left.get("error")
        and not right.get("error")
    )


def _assets_text(assets: list[dict[str, str]]) -> str:
    if not assets:
        return "-"
    return ", ".join(f"{item['asset']}={_asset_display_amount(item)}" for item in assets[:4])


def _asset_display_amount(item: dict[str, str]) -> str:
    total = item.get("total") or ""
    return total if _nonzero(total) else item.get("free", "")


def _asset_field(assets: list[dict[str, str]], code: str, field: str) -> str | None:
    for item in assets:
        if item["asset"] == code:
            return item.get(field) or None
    return None


def _num_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -8:
        dec = dec.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    text = format(dec.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _nonzero(value: Any) -> bool:
    try:
        return Decimal(str(value or "0")) != 0
    except (InvalidOperation, ValueError):
        return bool(value)


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _num_text(value)
        if text:
            return text
    return None


def _dash(value: Any) -> str:
    return str(value) if value not in (None, "") else "-"

def _int_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return str(int(value)) if isinstance(value, int | float) else "-"
