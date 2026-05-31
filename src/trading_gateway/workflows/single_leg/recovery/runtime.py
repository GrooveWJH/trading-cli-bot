from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_gateway.support.redaction import redact_text

Progress = Callable[[dict[str, Any]], None]
AddStep = Callable[[list[dict[str, Any]], dict[str, Any], Progress | None], None]


def cancel_or_restore(
    client: Any,
    order: dict[str, Any],
    symbol: str,
    steps: list[dict[str, Any]],
    progress: Progress | None,
    add_step: AddStep,
) -> dict[str, Any]:
    try:
        cancel = client.cancel_order(order["id"], symbol)
        add_step(steps, {"name": "timeout_cancel", "status": cancel.get("status", "submitted"), "order_id": order.get("id")}, progress)
    except Exception as exc:  # noqa: BLE001 - cancel races must not crash the CLI.
        add_step(steps, {"name": "cancel_restore", "status": "restore", "order_id": order.get("id"), "error": redact_text(exc)}, progress)
    verify = restore_order(client, symbol, order_id=order.get("id"), client_order_id=client_order_id(order))
    add_step(steps, {"name": "cancel_verify", "status": verify.get("status", "unknown"), "order_id": order.get("id")}, progress)
    return verify


def restore_order(client: Any, symbol: str, *, order_id: str | None = None, client_order_id: str | None = None) -> dict[str, Any]:
    if order_id:
        try:
            return client.fetch_order(order_id, symbol)
        except Exception:  # noqa: BLE001
            pass
    for row in safe_open_orders(client, symbol):
        cid = client_order_id_of(row)
        if (client_order_id and cid == client_order_id) or (not client_order_id and cid.startswith("aslab_")):
            return row
    return {"id": order_id, "status": "unknown"}


def owned_open_orders(client: Any, symbol: str) -> list[dict[str, Any]]:
    rows = []
    for row in safe_open_orders(client, symbol):
        if client_order_id_of(row).startswith("aslab_"):
            rows.append({"id": row.get("id"), "status": row.get("status"), "clientOrderId": client_order_id_of(row)})
    return rows


def safe_open_orders(client: Any, symbol: str) -> list[dict[str, Any]]:
    try:
        return client.fetch_open_orders(symbol) or []
    except Exception:  # noqa: BLE001
        return []


def client_order_id(order: dict[str, Any]) -> str:
    return client_order_id_of(order)


def client_order_id_of(order: dict[str, Any]) -> str:
    raw_info = order.get("info")
    raw_params = order.get("params")
    info = raw_info if isinstance(raw_info, dict) else {}
    params = raw_params if isinstance(raw_params, dict) else {}
    return str(order.get("clientOrderId") or order.get("client_order_id") or params.get("newClientOrderId") or info.get("clientOrderId") or "")


def is_maker_reject(exc: Exception) -> bool:
    return any(bit in str(exc).lower() for bit in ("limit_maker", "post only", "immediately match", "maker"))


def is_unknown_order_error(exc: Exception) -> bool:
    return "unknown order sent" in str(exc).lower()


def is_position_reduced_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(bit in text for bit in ("reduceonly", "reduce only", "no position", "insufficient position"))


def close_all_target(state: dict[str, Any], open_orders: list[dict[str, Any]], hint: str) -> dict[str, Any]:
    return {
        **state,
        "open_close_orders": open_orders,
        "owned_open_order_count": len(open_orders),
        "next_action_hint": hint,
    }
