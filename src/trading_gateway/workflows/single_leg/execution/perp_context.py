from __future__ import annotations

from typing import Any

from trading_gateway.support.redaction import redact_text


def build_runtime_order_context(client: Any, plan: dict[str, Any]) -> dict[str, Any]:
    params = dict((plan.get("order") or {}).get("params") or {})
    context: dict[str, Any] = {"params": params}
    if plan.get("market") != "perp":
        return context
    mode = fetch_position_mode(client)
    if mode.get("hedge"):
        params["positionSide"] = position_side(plan["action"])
        params.pop("reduceOnly", None)
    context["position_mode"] = mode
    return context


def fetch_position_mode(client: Any) -> dict[str, Any]:
    method = getattr(client, "fapiPrivateGetPositionSideDual", None) or getattr(client, "fapiprivate_get_positionside_dual", None)
    if not callable(method):
        return {"mode": "unknown", "hedge": False}
    try:
        payload = method() or {}
    except Exception as exc:  # noqa: BLE001
        return {"mode": "unknown", "hedge": False, "error": redact_text(exc)}
    dual = payload.get("dualSidePosition")
    hedge = dual is True or str(dual).lower() == "true"
    return {"mode": "hedge" if hedge else "oneway", "hedge": hedge}


def position_side(action: str) -> str:
    return "LONG" if action.endswith("long") else "SHORT"


def apply_position_params(params: dict[str, Any], plan: dict[str, Any], positions: list[dict[str, Any]], side: str) -> None:
    if plan.get("exchange") != "okx" or "tdMode" not in params:
        return
    for row in positions:
        if str(row.get("side") or "").lower() == side and row.get("marginMode"):
            params["tdMode"] = str(row["marginMode"]).lower()
            return


def fetch_positions(client: Any, symbol: str) -> list[dict[str, Any]]:
    return client.fetch_positions([symbol]) if hasattr(client, "fetch_positions") else []


def is_perp_close_all(plan: dict[str, Any]) -> bool:
    return plan.get("market") == "perp" and str(plan.get("quantity")).upper() == "ALL"
