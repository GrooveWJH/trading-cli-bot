from __future__ import annotations

from typing import Any

from trading_gateway.adapters.exchanges.single_leg import adapter_for


class StaticPriceClient:
    def __init__(self, symbol: str, market: str, last_price: float) -> None:
        market_payload: dict[str, Any] = {"symbol": symbol, market: True}
        if market == "swap":
            market_payload["contractSize"] = 1
        self.markets = {symbol: market_payload}
        self.last_price = float(last_price)

    def load_markets(self) -> dict:
        return self.markets

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": self.last_price}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.8f}"


class StaticBinanceLabClient:
    def __init__(self, symbol: str, market: str, last_price: float) -> None:
        self.symbol = symbol
        self.market = market
        self.last_price = float(last_price)
        self.markets = {symbol: self._market_payload()}

    def _market_payload(self) -> dict:
        if self.market == "perp":
            return {
                "symbol": self.symbol,
                "id": self.symbol.replace("/", "").replace(":USDT", ""),
                "contract": True,
                "contractSize": 1,
                "limits": {"amount": {"min": 0.001}, "cost": {"min": 5}},
                "precision": {"amount": 0.001},
            }
        return {
            "symbol": self.symbol,
            "id": self.symbol.replace("/", ""),
            "spot": True,
            "limits": {"amount": {"min": 0.00001}, "cost": {"min": 5}},
            "precision": {"amount": 0.00001},
        }

    def load_markets(self) -> dict:
        return self.markets

    def fetch_ticker(self, symbol: str) -> dict:
        return {"last": self.last_price, "close": self.last_price, "bid": self.last_price, "ask": self.last_price}

    def fetch_order_book(self, symbol: str) -> dict:
        return {"bids": [[self.last_price, 1000]], "asks": [[self.last_price, 1000]]}

    def fetch_balance(self) -> dict:
        return {"USDT": {"free": "100000", "used": "0", "total": "100000"}}

    def fetch_positions(self, symbols=None) -> list[dict]:
        return []

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        precision = 3 if self.market == "perp" else 5
        return f"{amount:.{precision}f}"

    def price_to_precision(self, symbol: str, price: float) -> str:
        return f"{price:.8f}"


class StaticLabClient(StaticBinanceLabClient):
    def __init__(self, exchange: str, symbol: str, market: str, last_price: float) -> None:
        self.exchange = exchange.lower()
        adapter = adapter_for(exchange, market)
        resolution = adapter.normalize_symbol(symbol)
        super().__init__(resolution.ccxt_symbol, market, last_price)
        payload = self._market_payload()
        payload["id"] = resolution.native_symbol
        payload["symbol"] = resolution.ccxt_symbol
        payload["base"] = resolution.canonical_symbol.split("/")[0]
        payload["quote"] = resolution.canonical_symbol.split("/")[1]
        if market == "perp" and self.exchange == "okx":
            payload.update({"contractSize": 0.01, "ctVal": 0.01})
        if market == "perp" and self.exchange == "gate":
            payload.update({"contractSize": 0.0001, "quanto_multiplier": 0.0001})
        self.markets = {
            resolution.ccxt_symbol: payload,
            resolution.canonical_symbol: payload,
            resolution.native_symbol: payload,
        }

    def _market_payload(self) -> dict:
        if self.market == "perp":
            min_amount = 1 if getattr(self, "exchange", "") == "gate" else 0.01 if getattr(self, "exchange", "") == "okx" else 0.001
            precision = 1 if getattr(self, "exchange", "") == "gate" else 0.01 if getattr(self, "exchange", "") == "okx" else 0.001
            return {
                "symbol": self.symbol,
                "id": self.symbol.replace("/", "").replace(":USDT", ""),
                "contract": True,
                "contractSize": 1,
                "limits": {"amount": {"min": min_amount}, "cost": {"min": 5}},
                "precision": {"amount": precision},
            }
        return super()._market_payload()

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        if self.market == "perp" and self.exchange == "gate":
            return str(int(amount))
        if self.market == "perp" and self.exchange == "okx":
            return f"{amount:.2f}"
        return super().amount_to_precision(symbol, amount)
