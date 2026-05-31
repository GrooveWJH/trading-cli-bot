from __future__ import annotations

from typing import Any

from trading_gateway.domain.models import CapabilityReport, MARKET_TYPES, SUPPORTED_EXCHANGES
from trading_gateway.infrastructure.exchange.factory import build_ccxt_client, close_client


def _has(client: Any, key: str) -> Any:
    data = getattr(client, "has", {}) or {}
    return data.get(key)


def build_capability_report(exchange: str, market: str, client: Any) -> CapabilityReport:
    notes: list[str] = []
    public_ok = bool(_has(client, "fetchTicker") is not False)
    private_read_ok = bool(_has(client, "fetchBalance")) and bool(_has(client, "fetchOpenOrders"))
    trade_supported = bool(_has(client, "createOrder") or _has(client, "createMarketOrder"))
    transfer_supported = bool(_has(client, "transfer"))
    adapter_trade_implemented = trade_supported
    adapter_transfer_implemented = transfer_supported
    if market == "swap" and exchange == "gate" and not bool(_has(client, "setMarginMode")):
        notes.append("gate.setMarginMode unavailable; margin mode must be manually verified")
    if market == "swap" and exchange == "mexc":
        notes.append("mexc.fetchPosition may be emulated; verify positions with fetchPositions")
    if not transfer_supported:
        notes.append("transfer is not advertised by ccxt for this client")
    return CapabilityReport(
        exchange=exchange,
        market=market,
        public_ok=public_ok,
        private_read_ok=private_read_ok,
        trade_supported=trade_supported,
        transfer_supported=transfer_supported,
        adapter_trade_implemented=adapter_trade_implemented,
        adapter_transfer_implemented=adapter_transfer_implemented,
        private_verified=False,
        notes=notes,
    )


def build_capability_matrix() -> list[CapabilityReport]:
    reports: list[CapabilityReport] = []
    for exchange in SUPPORTED_EXCHANGES:
        for market in MARKET_TYPES:
            client = build_ccxt_client(exchange, market)
            try:
                reports.append(build_capability_report(exchange, market, client))
            finally:
                close_client(client)
    return reports
