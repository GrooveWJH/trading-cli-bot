from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from trading_gateway.domain.models import SUPPORTED_EXCHANGES, TransferIntent
from trading_gateway.domain.route_universe import trading_symbols_for_exchange
from trading_gateway.app.config import get_gateway_config


def status_payload(active_job: dict[str, Any] | None = None) -> dict[str, Any]:
    config = get_gateway_config()
    return {
        "mode": "trading_gateway_web",
        "runtime": "local",
        "config_file": str(config.path),
        "env_file": str(config.dotenv_path),
        "credentials": credential_presence(),
        "safety": {
            "max_quote_usdt": config.lab_max_quote_usdt,
            "require_live_confirm": config.require_live_confirm,
            "perp_target_leverage": config.perp_execution.target_leverage,
        },
        "pair_journal": {
            "dir": str(config.pair_execution.journal_dir),
            "count": len(recent_pair_journals(limit=1000)),
        },
        "daemon": {
            "host": config.daemon.host,
            "port": config.daemon.port,
            "runtime_dir": str(config.daemon.runtime_dir),
        },
        "web": {
            "polling": {
                "daemon_status_ms": config.web_polling.daemon_status_ms,
                "summary_ms": config.web_polling.summary_ms,
                "snapshot_ms": config.web_polling.snapshot_ms,
                "jobs_ms": config.web_polling.jobs_ms,
                "journals_ms": config.web_polling.journals_ms,
                "live_job_ms": config.web_polling.live_job_ms,
                "query_stale_ms": config.web_polling.query_stale_ms,
            },
        },
        "active_live_job": active_job,
    }


def credential_presence() -> dict[str, dict[str, bool]]:
    config = get_gateway_config()
    rows: dict[str, dict[str, bool]] = {}
    for exchange in SUPPORTED_EXCHANGES:
        spec = config.credential_envs[exchange]
        rows[exchange] = {
            "api_key": bool(os.getenv(spec.key_env)),
            "api_secret": bool(os.getenv(spec.secret_env)),
            "password": bool(os.getenv(spec.password_env or "")) if spec.password_env else False,
        }
    return rows


def recent_pair_journals(limit: int = 20) -> list[dict[str, Any]]:
    journal_dir = get_gateway_config().pair_execution.journal_dir
    if not journal_dir.exists():
        return []
    rows = []
    for path in sorted(journal_dir.glob("aspair_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        rows.append({"pair_id": path.stem, "path": str(path), "mtime": path.stat().st_mtime})
    return rows


def transfer_intent(body: dict[str, Any]) -> TransferIntent:
    return TransferIntent(
        exchange=str(body.get("exchange") or ""),
        code=str(body.get("code") or ""),
        amount=float(body.get("amount") or 0),
        from_account=str(body.get("from_account") or body.get("from") or ""),
        to_account=str(body.get("to_account") or body.get("to") or ""),
    )


def binance_universe() -> dict[str, Any]:
    return trading_symbols_for_exchange("binance", get_gateway_config().route_universe)


def static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"
