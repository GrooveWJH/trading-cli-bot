from __future__ import annotations

from typing import Any

from trading_gateway.workflows.overview.snapshot.model.models import AssetBalance, PerpPosition, WalletAccount
from trading_gateway.workflows.overview.snapshot.parsing.positions import binance_position, gate_position, is_okx_swap_inst, mexc_position, okx_position
from trading_gateway.workflows.overview.snapshot.utilities.utils import add, asset_balance, first, nonzero


def parse_binance_spot(raw: dict[str, Any], *, nonzero_only: bool = True) -> WalletAccount:
    rows = _list(raw.get("balances"))
    assets = [
        asset_balance(row.get("asset"), add(row.get("free"), row.get("locked")), row.get("free"), row.get("locked"), source_account="spot")
        for row in rows
        if _keep_asset(row.get("free"), row.get("locked"), nonzero_only)
    ]
    return _spot_account(assets, rows, nonzero_only, "spot")


def parse_okx_spot(raw: dict[str, Any], *, nonzero_only: bool = True) -> WalletAccount:
    details = _okx_details(raw)
    assets = [
        asset_balance(row.get("ccy"), row.get("eq"), row.get("availBal"), row.get("frozenBal"), source_account="unified")
        for row in details
        if _keep_asset(row.get("eq"), row.get("frozenBal"), nonzero_only)
    ]
    return _spot_account(assets, details, nonzero_only, "unified")


def parse_gate_spot(raw: Any, *, nonzero_only: bool = True) -> WalletAccount:
    rows = _list(raw)
    assets = [
        asset_balance(row.get("currency"), add(row.get("available"), row.get("locked")), row.get("available"), row.get("locked"), source_account="spot")
        for row in rows
        if _keep_asset(row.get("available"), row.get("locked"), nonzero_only)
    ]
    return _spot_account(assets, rows, nonzero_only, "spot")


def parse_mexc_spot(raw: dict[str, Any], *, nonzero_only: bool = True) -> WalletAccount:
    rows = _list(raw.get("balances"))
    assets = [
        asset_balance(row.get("asset"), add(row.get("free"), row.get("locked")), row.get("free"), row.get("locked"), source_account="spot")
        for row in rows
        if _keep_asset(row.get("free"), row.get("locked"), nonzero_only)
    ]
    return _spot_account(assets, rows, nonzero_only, "spot")


def parse_binance_swap(
    account: dict[str, Any],
    positions: Any,
    *,
    include_empty_positions: bool = False,
) -> WalletAccount:
    margin = [asset_balance("USDT", account.get("totalWalletBalance"), account.get("availableBalance"), None, source_account="swap")]
    parsed = [binance_position(row) for row in _list(positions) if _keep_position(row.get("positionAmt"), include_empty_positions)]
    return _perp_account(margin, parsed, "oneway", "perp")


def parse_okx_swap(raw: dict[str, Any], *, include_empty_positions: bool = False, balance: dict[str, Any] | None = None) -> WalletAccount:
    parsed = [okx_position(row) for row in _list(raw.get("data")) if is_okx_swap_inst(row) and _keep_position(row.get("pos"), include_empty_positions)]
    margin = _okx_margin_assets(balance or {})
    return _perp_account(margin, parsed, "okx", "unified")


def parse_gate_swap(
    account: dict[str, Any],
    positions: Any,
    *,
    include_empty_positions: bool = False,
) -> WalletAccount:
    margin = [asset_balance("USDT", account.get("total"), account.get("available"), None, source_account="swap")]
    parsed = [gate_position(row) for row in _list(positions) if _keep_position(row.get("size"), include_empty_positions)]
    return _perp_account(margin, parsed, "oneway", "perp")


def parse_mexc_swap(
    assets: dict[str, Any],
    positions: dict[str, Any],
    *,
    include_empty_positions: bool = False,
) -> WalletAccount:
    margin = [
        asset_balance(row.get("currency"), first(row.get("equity"), row.get("cashBalance")), row.get("availableBalance"), row.get("frozenBalance"), source_account="swap")
        for row in _list(assets.get("data"))
        if _keep_asset(first(row.get("equity"), row.get("cashBalance")), row.get("frozenBalance"), True)
    ]
    parsed = [mexc_position(row) for row in _list(positions.get("data")) if _keep_position(row.get("holdVol"), include_empty_positions)]
    return _perp_account(margin, parsed, "mexc", "perp")


def _spot_account(assets: list[AssetBalance], raw_rows: list[dict[str, Any]], nonzero_only: bool, account_type: str) -> WalletAccount:
    zero_count = sum(1 for row in raw_rows if not _row_nonzero(row))
    return WalletAccount(
        market="spot",
        account_type=account_type,
        assets=sorted(assets, key=lambda row: _asset_sort_key(row.asset)),
        asset_count=len(assets),
        hidden_zero_count=zero_count if nonzero_only else 0,
        positions=[],
        open_positions_count=0,
        position_mode=None,
        equity_usdt=_usdt_asset_field(assets, "total"),
        available_usdt=_usdt_asset_field(assets, "free"),
    )


def _perp_account(assets: list[AssetBalance], positions: list[PerpPosition], position_mode: str, account_type: str) -> WalletAccount:
    sorted_assets = sorted(assets, key=lambda row: _asset_sort_key(row.asset))
    sorted_positions = sorted(positions, key=lambda row: row.symbol)
    return WalletAccount(
        market="perp",
        account_type=account_type,
        assets=sorted_assets,
        asset_count=len(sorted_assets),
        hidden_zero_count=0,
        positions=sorted_positions,
        open_positions_count=sum(1 for row in sorted_positions if row.side != "flat"),
        position_mode=position_mode,
        equity_usdt=_usdt_asset_field(sorted_assets, "total"),
        available_usdt=_usdt_asset_field(sorted_assets, "free"),
    )


def _okx_details(raw: dict[str, Any]) -> list[dict[str, Any]]:
    data = raw.get("data") if isinstance(raw, dict) else []
    first_row = data[0] if isinstance(data, list) and data else {}
    return _list(first_row.get("details"))


def _okx_margin_assets(raw: dict[str, Any]) -> list[AssetBalance]:
    return [
        asset_balance(row.get("ccy"), row.get("eq"), row.get("availBal"), row.get("frozenBal"), source_account="unified")
        for row in _okx_details(raw)
        if _keep_asset(row.get("eq"), row.get("frozenBal"), True)
    ]


def _keep_asset(total: Any, locked: Any, nonzero_only: bool) -> bool:
    return True if not nonzero_only else nonzero(total) or nonzero(locked)


def _keep_position(amount: Any, include_empty_positions: bool) -> bool:
    return include_empty_positions or nonzero(amount)


def _row_nonzero(row: dict[str, Any]) -> bool:
    keys = ("free", "locked", "available", "eq", "frozenBal", "total", "amount")
    return any(nonzero(row.get(key)) for key in keys)


def _list(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _asset_sort_key(asset: str) -> tuple[int, str]:
    preferred = {"USDT": 0, "BTC": 1}
    return preferred.get(asset, 10), asset


def _usdt_asset_field(assets: list[AssetBalance], field: str) -> str | None:
    for row in assets:
        if row.asset == "USDT":
            return getattr(row, field, None) or None
    return None
