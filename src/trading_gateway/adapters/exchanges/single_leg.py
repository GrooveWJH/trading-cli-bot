from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_gateway.app.config import get_gateway_config


@dataclass(frozen=True)
class SymbolResolution:
    canonical_symbol: str
    ccxt_symbol: str
    native_symbol: str


class SingleLegAdapter:
    def __init__(self, exchange: str, market: str) -> None:
        self.exchange = exchange.lower()
        self.market = market.lower()

    def normalize_symbol(self, symbol: str) -> SymbolResolution:
        base, quote = _base_quote(symbol)
        canonical = f"{base}/{quote}"
        if self.market == "spot":
            if self.exchange == "okx":
                return SymbolResolution(canonical, canonical, f"{base}-{quote}")
            if self.exchange == "gate":
                return SymbolResolution(canonical, canonical, f"{base}_{quote}")
            return SymbolResolution(canonical, canonical, f"{base}{quote}")
        if self.exchange == "binance":
            return SymbolResolution(canonical, f"{base}/{quote}:{quote}", f"{base}{quote}")
        if self.exchange == "okx":
            native = f"{base}-{quote}-SWAP"
            return SymbolResolution(canonical, f"{base}/{quote}:{quote}", native)
        if self.exchange == "gate":
            native = f"{base}_{quote}"
            return SymbolResolution(canonical, f"{base}/{quote}:{quote}", native)
        if self.exchange == "mexc":
            native = f"{base}_{quote}"
            return SymbolResolution(canonical, f"{base}/{quote}:{quote}", native)
        raise ValueError(f"unsupported exchange: {self.exchange}")

    def market_lookup(self, client: Any, resolution: SymbolResolution) -> dict[str, Any]:
        markets = getattr(client, "markets", None) or client.load_markets()
        keys = [resolution.ccxt_symbol, resolution.canonical_symbol, resolution.native_symbol]
        for key in keys:
            if key in markets:
                return markets[key]
        for row in markets.values():
            if str(row.get("id") or "").upper() == resolution.native_symbol.upper():
                return row
            if str(row.get("symbol") or "").upper() in {key.upper() for key in keys}:
                return row
        raise ValueError(f"symbol not found in {self.exchange} {self.market} markets: {resolution.canonical_symbol}")

    def base_asset(self, resolution: SymbolResolution, market: dict[str, Any]) -> str:
        return str(market.get("base") or resolution.canonical_symbol.split("/")[0]).upper()

    def quote_asset(self, resolution: SymbolResolution, market: dict[str, Any]) -> str:
        return str(market.get("quote") or resolution.canonical_symbol.split("/")[1]).upper()

    def contract_size(self, market: dict[str, Any]) -> float:
        if self.market == "spot":
            return 1.0
        for key in ("contractSize", "ctVal", "quanto_multiplier"):
            value = _positive(market.get(key) or (market.get("info") or {}).get(key))
            if value > 0:
                return value
        return 1.0

    def base_to_order_amount(self, base_quantity: float, market: dict[str, Any]) -> float:
        size = self.contract_size(market)
        return base_quantity / size if self.market == "perp" and size > 0 else base_quantity

    def order_type(self, bbo: bool) -> str:
        config = get_gateway_config()
        if self.market == "spot":
            if self.exchange == "gate":
                return "limit"
            return config.spot_bbo_order_type
        return config.bbo_order_type if bbo else "market"

    def order_params(self, action: str, bbo: bool) -> dict[str, Any]:
        config = get_gateway_config()
        if self.market == "spot":
            if self.exchange == "binance":
                return {"postOnly": True} if config.spot_bbo_post_only else {}
            if self.exchange == "gate":
                return {"timeInForce": "poc"}
            return {"postOnly": True}
        params: dict[str, Any] = {}
        if self.exchange == "binance":
            if bbo:
                params["timeInForce"] = config.bbo_time_in_force
                params["priceMatch"] = config.bbo_price_match
            if action.startswith("close-"):
                params["reduceOnly"] = True
        elif self.exchange == "okx":
            params["tdMode"] = "cross"
            params["ordType"] = "post_only" if bbo else "market"
            if action.startswith("close-"):
                params["reduceOnly"] = True
        elif self.exchange == "gate":
            if bbo:
                params["timeInForce"] = "poc"
            if action.startswith("close-"):
                params["reduceOnly"] = True
        return params

    def spot_rescue_order(self) -> tuple[str, dict[str, Any]] | None:
        if self.market != "spot":
            return None
        if self.exchange == "binance":
            return ("limit", {"timeInForce": "IOC"})
        if self.exchange == "okx":
            return ("limit", {"ordType": "ioc"})
        if self.exchange == "gate":
            return ("limit", {"timeInForce": "ioc"})
        return None

    def maker_price(self, client: Any, symbol: str, side: str, params: dict[str, Any]) -> float | None:
        if params.get("priceMatch"):
            return None
        book = client.fetch_order_book(symbol)
        rows = book.get("bids") if side == "buy" else book.get("asks")
        if not rows:
            raise ValueError(f"{self.exchange} order book has no {'bid' if side == 'buy' else 'ask'} price for {symbol}")
        price = float(rows[0][0])
        method = getattr(client, "price_to_precision", None)
        return float(method(symbol, price)) if callable(method) else price

    def supports_live(self) -> bool:
        if self.exchange == "mexc" and self.market == "perp":
            return False
        return self.exchange in {"binance", "okx", "gate", "mexc"}

    def unsupported_reason(self) -> str:
        if self.exchange == "mexc" and self.market == "perp":
            return "mexc perp trading is not enabled in Trading Gateway v1"
        return f"{self.exchange} {self.market} trading is not enabled in Trading Gateway v1"

    def confirm_exchange(self) -> str:
        return self.exchange.upper()


def adapter_for(exchange: str, market: str) -> SingleLegAdapter:
    name = str(exchange or "").strip().lower()
    kind = str(market or "").strip().lower()
    if kind not in {"spot", "perp"}:
        raise ValueError("market must be spot or perp")
    if name not in {"binance", "okx", "gate", "mexc"}:
        raise ValueError("exchange must be one of binance, okx, gate, mexc")
    return SingleLegAdapter(name, kind)


def _base_quote(symbol: str) -> tuple[str, str]:
    text = str(symbol or "").strip().upper()
    text = text.split(":")[0]
    if "/" in text:
        base, quote = text.split("/", 1)
        return base, quote
    if text.endswith("-SWAP"):
        text = text.removesuffix("-SWAP")
    if "-" in text:
        base, quote = text.split("-", 1)
        return base, quote
    if "_" in text:
        base, quote = text.split("_", 1)
        return base, quote
    if text.endswith("USDT"):
        return text.removesuffix("USDT"), "USDT"
    raise ValueError(f"unsupported symbol format: {symbol}; use BASE/USDT, e.g. BTC/USDT")


def _positive(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0
