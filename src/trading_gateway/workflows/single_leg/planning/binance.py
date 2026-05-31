from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_gateway.adapters.exchanges.rules import amount_step, min_executable, plan_quantity_from_rules
from trading_gateway.app.config import get_gateway_config
from trading_gateway.domain.models import format_decimal
from trading_gateway.domain.route_universe import validate_trading_symbol
from trading_gateway.support.redaction import redact_mapping


@dataclass(frozen=True)
class BinanceLabIntent:
    market: str
    action: str
    symbol: str
    quote_usdt: float | None = None
    bbo: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", clean_value(self.market))
        object.__setattr__(self, "action", clean_value(self.action))
        object.__setattr__(self, "symbol", normalize_binance_symbol(self.symbol, self.market))
        if self.market not in {"spot", "perp"}:
            raise ValueError("market must be spot or perp")
        actions = {"buy", "sell"} if self.market == "spot" else {"open-long", "open-short", "close-long", "close-short"}
        if self.action not in actions:
            raise ValueError(f"unsupported {self.market} action: {self.action}")
        if self.market == "spot" and self.action == "buy" and self.quote_usdt is None:
            raise ValueError("quote_usdt is required for spot buy")
        if self.quote_usdt is not None and float(self.quote_usdt) <= 0:
            raise ValueError("quote_usdt must be positive")


def normalize_binance_symbol(symbol: str, market: str) -> str:
    text = str(symbol or "").strip().upper()
    if "/" in text:
        core = text.split(":")[0]
        return f"{core}:USDT" if market == "perp" else core
    if text.endswith("USDT"):
        base = text.removesuffix("USDT")
        return f"{base}/USDT:USDT" if market == "perp" else f"{base}/USDT"
    return text


def build_binance_trade_plan(client: Any, intent: BinanceLabIntent, universe_path: str | Path | None = None) -> dict[str, Any]:
    config = get_gateway_config()
    market = market_for(client, intent.symbol)
    ticker = client.fetch_ticker(intent.symbol) or {}
    last = positive_float(ticker.get("last") or ticker.get("close") or ticker.get("ask") or ticker.get("bid"), "last price")
    quote = quote_for_plan(intent, last, market)
    quantity_plan = plan_quantity_from_rules(client, intent.symbol, market, quote, last, spot_buy=False)
    qty = None if is_all_quantity(intent) else quantity_plan["quantity"]
    actual_quote = quantity_plan["actual_quote"]
    warnings = universe_warnings(intent, universe_path)
    if intent.quote_usdt is not None and quantity_plan["below_minimum"]:
        warnings.append(
            {
                "code": "below_minimum_quantity_notional",
                "message": "requested quote is below Binance minimum executable quantity; "
                f"min_executable_quote_usdt={quantity_plan['min_executable_quote']}",
            }
        )
    if intent.quote_usdt is not None and actual_quote > config.lab_max_quote_usdt:
        warnings.append({"code": "above_lab_safety_cap", "message": "planned notional is above local lab safety cap"})
    order_type = order_type_for_plan(intent, config)
    can_execute = not warnings and (intent.quote_usdt is None or quote <= config.lab_max_quote_usdt)
    preview = {
        "kind": "legacy_binance_plan_preview",
        "planned_delta_quantity": "ALL" if qty is None else format_decimal(qty),
        "current_quantity": None,
        "target_quantity": 0.0 if qty is None and intent.action.startswith("close-") else None,
        "remaining_quantity": "ALL" if qty is None else format_decimal(qty),
        "estimated_quote_usdt": actual_quote,
        "submit_order": True,
    }
    return {
        "exchange": "binance",
        "market": intent.market,
        "action": intent.action,
        "symbol": intent.symbol,
        "base_asset": base_asset(intent.symbol, market),
        "quote_asset": quote_asset(intent.symbol, market),
        "target_asset": base_asset(intent.symbol, market) if intent.market == "spot" else None,
        "target_leverage": config.perp_target_leverage if intent.market == "perp" else None,
        "requested_quote_usdt": intent.quote_usdt,
        "last_price": last,
        "quantity": "ALL" if qty is None else format_decimal(qty),
        "quantity_step": format_decimal(amount_step(market)),
        "planned_delta_quantity": None if qty is None else format_decimal(qty),
        "min_executable_quote_usdt": quantity_plan["min_executable_quote"],
        "min_executable_quantity": format_decimal(quantity_plan["min_executable_quantity"]),
        "can_execute": can_execute,
        "warnings": warnings,
        "blocked_reason": warnings[0]["message"] if warnings else None,
        "confirm_phrase": confirm_phrase(intent, qty),
        "execution_preview": preview,
        "order": {
            "symbol": intent.symbol,
            "type": order_type,
            "side": side_for_action(intent.action),
            "amount": None if qty is None else qty,
            "price": None,
            "params": order_params(intent),
        },
    }


def run_binance_preflight(spot_client: Any, swap_client: Any, symbol: str = "BTCUSDT") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    spot_symbol = normalize_binance_symbol(symbol, "spot")
    swap_symbol = normalize_binance_symbol(symbol, "perp")
    run_check(checks, "spot_balance", spot_client.fetch_balance)
    run_check(checks, "swap_balance", swap_client.fetch_balance)
    run_check(checks, "swap_positions", lambda: swap_client.fetch_positions([swap_symbol]))
    run_check(checks, "swap_open_orders", lambda: swap_client.fetch_open_orders(swap_symbol))
    ok = all(row["status"] == "ok" for row in checks)
    return redact_mapping({"mode": "single_leg_preflight", "ok": ok, "spot_symbol": spot_symbol, "swap_symbol": swap_symbol, "checks": checks})


def run_check(checks: list[dict[str, Any]], name: str, fn: Any) -> None:
    try:
        fn()
        checks.append({"name": name, "status": "ok"})
    except Exception as exc:  # pragma: no cover
        checks.append({"name": name, "status": "error", "error": str(exc)})


def market_for(client: Any, symbol: str) -> dict[str, Any]:
    markets = getattr(client, "markets", None) or client.load_markets()
    market = (markets or {}).get(symbol)
    if not market:
        raise ValueError(f"symbol not found in Binance markets: {symbol}")
    return market


def universe_warnings(intent: BinanceLabIntent, path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    validation = validate_trading_symbol(intent.symbol, intent.market, "binance", path)
    return [] if validation["supported"] else [{"code": "symbol_not_supported", "message": validation["reason"]}]


def quote_for_plan(intent: BinanceLabIntent, last: float, market: dict[str, Any]) -> float:
    if intent.quote_usdt is not None:
        return float(intent.quote_usdt)
    return min_executable(market, last)["quote"]


def order_params(intent: BinanceLabIntent) -> dict[str, Any]:
    if intent.market == "spot":
        config = get_gateway_config()
        return {"postOnly": True} if config.spot_bbo_post_only else {}
    config = get_gateway_config()
    params: dict[str, Any] = {"timeInForce": config.bbo_time_in_force}
    if intent.bbo:
        params["timeInForce"] = config.bbo_time_in_force
        params["priceMatch"] = config.bbo_price_match
    if intent.action.startswith("close-"):
        params["reduceOnly"] = True
    return params


def side_for_action(action: str) -> str:
    return {
        "buy": "buy",
        "sell": "sell",
        "open-long": "buy",
        "open-short": "sell",
        "close-long": "sell",
        "close-short": "buy",
    }[action]


def is_all_quantity(intent: BinanceLabIntent) -> bool:
    if intent.market == "spot":
        return intent.action == "sell" and intent.quote_usdt is None
    return intent.action.startswith("close-") and intent.quote_usdt is None


def order_type_for_plan(intent: BinanceLabIntent, config: Any) -> str:
    if intent.market == "spot":
        return config.spot_bbo_order_type
    return config.bbo_order_type if intent.bbo else "market"


def base_asset(symbol: str, market: dict[str, Any]) -> str:
    return str(market.get("base") or symbol.split("/")[0]).upper()


def quote_asset(symbol: str, market: dict[str, Any]) -> str:
    if market.get("quote"):
        return str(market["quote"]).upper()
    return symbol.split(":")[0].split("/")[1].upper() if "/" in symbol else "USDT"


def confirm_phrase(intent: BinanceLabIntent, quantity: float | None) -> str:
    action = intent.action.replace("-", "_").upper()
    if intent.quote_usdt is not None:
        qty = f"QUOTE_{format_decimal(float(intent.quote_usdt))}"
    else:
        qty = "ALL" if quantity is None else format_decimal(quantity)
    return f"LIVE_BINANCE_{intent.market.upper()}_{action}:{confirm_symbol(intent.symbol)}:{qty}"


def confirm_symbol(symbol: str) -> str:
    return symbol.split(":")[0].replace("/", "")


def positive_float(value: Any, label: str) -> float:
    number = float(value or 0)
    if number <= 0:
        raise ValueError(f"{label} unavailable")
    return number


def clean_value(value: str) -> str:
    return str(value or "").strip().lower()
