from __future__ import annotations

from typing import Any


def target_side(action: str) -> str:
    return "long" if action.endswith("long") else "short"


def target_quantity(plan: dict[str, Any], current: float) -> float:
    amount = plan.get("planned_delta_quantity") or plan["order"].get("amount")
    planned = current if amount is None else float(amount)
    if plan["action"].startswith("open-"):
        return current + planned
    return max(0.0, current - min(current, planned))


def remaining_quantity(action: str, current: float, target: float) -> float:
    return max(0.0, target - current) if action.startswith("open-") else max(0.0, current - target)


def target_reached(action: str, current: float, target: float, tolerance: float) -> bool:
    if action.startswith("open-") and target > 0 and current <= 0:
        return False
    return current > target - tolerance if action.startswith("open-") else current < target + tolerance


def target_state(current: float, target: float, tolerance: float) -> dict[str, float]:
    return {"current_quantity": current, "target_quantity": target, "remaining_quantity": abs(target - current), "tolerance_quantity": tolerance}


def position_quantity(positions: list[dict[str, Any]], symbol: str, side: str, hedge: bool) -> float:
    for row in positions:
        if not _same_symbol(row, symbol):
            continue
        row_side = _row_side(row)
        quantity = abs(_row_signed_quantity(row) * _contract_size(row))
        if hedge and row_side == side:
            return quantity
        if not hedge and row_side == side:
            return quantity
    return 0.0


def _same_symbol(row: dict[str, Any], symbol: str) -> bool:
    row_symbol = str(row.get("symbol") or "")
    info_symbol = str((row.get("info") or {}).get("symbol") or "")
    compact = symbol.split(":")[0].replace("/", "")
    dash_swap = symbol.replace("/", "-").replace(":USDT", "-SWAP")
    underscore = symbol.split(":")[0].replace("/", "_")
    variants = {symbol, symbol.split(":")[0], compact, dash_swap, underscore}
    return row_symbol in variants or info_symbol in variants


def _row_side(row: dict[str, Any]) -> str:
    raw = str((row.get("info") or {}).get("positionSide") or row.get("side") or "").lower()
    if raw in {"long", "short"}:
        return raw
    return "short" if _row_signed_quantity(row) < 0 else "long"


def _row_signed_quantity(row: dict[str, Any]) -> float:
    info = row.get("info") or {}
    for value in (info.get("positionAmt"), row.get("contracts")):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            continue
        if number:
            return number
    return 0.0


def _contract_size(row: dict[str, Any]) -> float:
    for value in (row.get("contractSize"), (row.get("info") or {}).get("contractSize")):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 1.0
