from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AssetBalance:
    asset: str
    total: str
    free: str
    locked: str
    borrowed: str = "0"
    interest: str = "0"
    usdt_value: str | None = None
    source_account: str = "spot"
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerpPosition:
    symbol: str
    base: str
    quote: str
    settle: str
    side: str
    size: str
    contracts: str
    contract_size: str
    notional_usdt: str
    entry_price: str
    mark_price: str
    liq_price: str
    leverage: str
    margin_mode: str
    unrealized_pnl: str
    realized_pnl: str | None = None
    percentage: str | None = None
    updated_at_ms: int | None = None
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WalletAccount:
    market: str
    account_type: str
    assets: list[AssetBalance]
    asset_count: int
    hidden_zero_count: int
    positions: list[PerpPosition]
    open_positions_count: int
    position_mode: str | None = None
    equity_usdt: str | None = None
    available_usdt: str | None = None
    query_ms: int = 0
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
