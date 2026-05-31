from __future__ import annotations

from typing import Any

from trading_gateway.workflows.pair_trade.planning.helpers import hedge_mode


def build_pair_order_params(
    adapter: Any,
    client: Any,
    leg: str,
    client_order_id: str,
    *,
    post_only: bool = True,
    reduce_only: bool = False,
) -> dict[str, Any]:
    params = dict(adapter.order_params("close-short" if reduce_only else "open-short", post_only))
    params.setdefault("newClientOrderId", client_order_id)
    if leg == "spot":
        return params
    if adapter.exchange == "binance" and hedge_mode(client):
        params["positionSide"] = "SHORT"
    if reduce_only:
        params["reduceOnly"] = True
    return params


def build_force_close_params(adapter: Any, plan: dict[str, Any], base_params: dict[str, Any]) -> dict[str, Any]:
    params = dict(base_params)
    for key in ("priceMatch", "postOnly", "timeInForce"):
        params.pop(key, None)
    if params.get("ordType") in {"post_only", "poc"}:
        params.pop("ordType", None)
    if adapter.exchange == "okx":
        params["ordType"] = "market"
    elif adapter.exchange == "gate":
        params["timeInForce"] = "ioc"
    if str(plan.get("action") or "").startswith("close-") and "positionSide" not in params:
        params["reduceOnly"] = True
    return params
