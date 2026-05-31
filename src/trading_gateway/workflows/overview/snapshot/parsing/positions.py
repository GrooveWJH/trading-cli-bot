from __future__ import annotations

from typing import Any

from trading_gateway.workflows.overview.snapshot.model.models import PerpPosition
from trading_gateway.workflows.overview.snapshot.utilities.utils import decimal, first, num, side_from_amount, signed_size


def binance_position(row: dict[str, Any]) -> PerpPosition:
    symbol = str(row.get("symbol") or "")
    base, quote = _split_suffix(symbol, "USDT")
    return PerpPosition(
        symbol=symbol,
        base=base,
        quote=quote,
        settle=quote,
        side=side_from_amount(row.get("positionAmt")),
        size=num(row.get("positionAmt")),
        contracts=num(abs(decimal(row.get("positionAmt")))),
        contract_size="1",
        notional_usdt=num(row.get("notional")),
        entry_price=num(row.get("entryPrice")),
        mark_price=num(row.get("markPrice")),
        liq_price=num(row.get("liquidationPrice")),
        leverage=num(row.get("leverage")),
        margin_mode=str(row.get("marginType") or "-"),
        unrealized_pnl=num(row.get("unRealizedProfit")),
        updated_at_ms=_int_or_none(row.get("updateTime")),
    )


def okx_position(row: dict[str, Any]) -> PerpPosition:
    side = _okx_side(row)
    base, quote, settle = _split_okx_inst(str(row.get("instId") or ""))
    return PerpPosition(
        symbol=str(row.get("instId") or ""),
        base=base,
        quote=quote,
        settle=settle,
        side=side,
        size=signed_size(row.get("pos"), side),
        contracts=num(abs(decimal(row.get("pos")))),
        contract_size=num(first(row.get("ctVal"), "1")),
        notional_usdt=num(first(row.get("notionalUsd"), row.get("notional"))),
        entry_price=num(row.get("avgPx")),
        mark_price=num(row.get("markPx")),
        liq_price=num(row.get("liqPx")),
        leverage=num(row.get("lever")),
        margin_mode=str(row.get("mgnMode") or "-"),
        unrealized_pnl=num(row.get("upl")),
        updated_at_ms=_int_or_none(first(row.get("uTime"), row.get("cTime"))),
    )


def gate_position(row: dict[str, Any]) -> PerpPosition:
    symbol = str(row.get("contract") or "")
    base, quote = _split_delimited(symbol)
    return PerpPosition(
        symbol=symbol,
        base=base,
        quote=quote,
        settle=quote,
        side=side_from_amount(row.get("size")),
        size=num(row.get("size")),
        contracts=num(abs(decimal(row.get("size")))),
        contract_size=num(first(row.get("quanto_multiplier"), "1")),
        notional_usdt=num(row.get("value")),
        entry_price=num(row.get("entry_price")),
        mark_price=num(row.get("mark_price")),
        liq_price=num(row.get("liq_price")),
        leverage=num(row.get("lever")),
        margin_mode=str(row.get("pos_margin_mode") or "-"),
        unrealized_pnl=num(row.get("unrealised_pnl")),
        updated_at_ms=_int_or_none(row.get("update_time_ms")),
    )


def mexc_position(row: dict[str, Any]) -> PerpPosition:
    symbol = str(first(row.get("symbol"), row.get("contract")) or "")
    side = _mexc_side(row)
    base, quote = _split_delimited(symbol)
    return PerpPosition(
        symbol=symbol,
        base=base,
        quote=quote,
        settle=quote,
        side=side,
        size=signed_size(row.get("holdVol"), side),
        contracts=num(abs(decimal(row.get("holdVol")))),
        contract_size=num(first(row.get("contractSize"), "1")),
        notional_usdt=num(first(row.get("value"), row.get("positionValue"))),
        entry_price=num(first(row.get("openAvgPrice"), row.get("holdAvgPrice"))),
        mark_price=num(row.get("markPrice")),
        liq_price=num(row.get("liquidatePrice")),
        leverage=num(row.get("leverage")),
        margin_mode=str(first(row.get("marginMode"), row.get("positionMode"), "-")),
        unrealized_pnl=num(first(row.get("unrealized"), row.get("unrealised"), row.get("unrealizedPnl"))),
        updated_at_ms=_int_or_none(first(row.get("updateTime"), row.get("createTime"))),
    )


def is_okx_swap_inst(row: dict[str, Any]) -> bool:
    inst_type = str(row.get("instType") or "").upper()
    inst_id = str(row.get("instId") or "").upper()
    return not inst_type or inst_type == "SWAP" or inst_id.endswith("-SWAP")


def _okx_side(row: dict[str, Any]) -> str:
    pos_side = str(row.get("posSide") or "").lower()
    return pos_side if pos_side in {"long", "short"} else side_from_amount(row.get("pos"))


def _mexc_side(row: dict[str, Any]) -> str:
    raw = str(first(row.get("positionType"), row.get("side"), "")).lower()
    if raw in {"1", "long", "buy"}:
        return "long"
    if raw in {"2", "short", "sell"}:
        return "short"
    return side_from_amount(row.get("holdVol"))


def _split_suffix(symbol: str, suffix: str) -> tuple[str, str]:
    return (symbol[: -len(suffix)], suffix) if symbol.endswith(suffix) else (symbol, "")


def _split_delimited(symbol: str) -> tuple[str, str]:
    parts = symbol.replace("-", "_").split("_")
    return (parts[0], parts[1]) if len(parts) >= 2 else (symbol, "")


def _split_okx_inst(symbol: str) -> tuple[str, str, str]:
    parts = symbol.split("-")
    if len(parts) >= 3:
        return parts[0], parts[1], parts[1]
    base, quote = _split_delimited(symbol)
    return base, quote, ""


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
