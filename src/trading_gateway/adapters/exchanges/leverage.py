from __future__ import annotations

from typing import Any

from trading_gateway.support.redaction import redact_text


def ensure_perp_leverage(client: Any, symbol: str, leverage: int) -> dict[str, Any]:
    if int(leverage) < 1:
        return {"status": "error", "target_leverage": leverage, "error": "target leverage must be >= 1"}
    set_leverage = getattr(client, "set_leverage", None)
    if not callable(set_leverage):
        return {"status": "unavailable", "target_leverage": leverage, "error": "client.set_leverage unavailable"}
    try:
        set_leverage(int(leverage), symbol)
    except Exception as exc:  # noqa: BLE001 - exchange configuration errors must become structured reports.
        return {"status": "error", "target_leverage": leverage, "error": redact_text(exc)}
    return {"status": "ok", "target_leverage": int(leverage)}
