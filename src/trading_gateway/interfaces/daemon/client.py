from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from trading_gateway.app.config import DEFAULT_CONFIG_FILE, get_gateway_config


class DaemonClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def daemon_runtime_file() -> Path:
    config = get_gateway_config()
    return config.daemon.runtime_dir / "daemon.json"


def daemon_pid_file() -> Path:
    config = get_gateway_config()
    return config.daemon.runtime_dir / "daemon.pid"


def read_daemon_metadata() -> dict[str, Any] | None:
    path = daemon_runtime_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_daemon_metadata(payload: dict[str, Any]) -> Path:
    path = daemon_runtime_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_daemon_pid(pid: int) -> Path:
    path = daemon_pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")
    return path


def clear_daemon_runtime_files() -> None:
    for path in (daemon_runtime_file(), daemon_pid_file()):
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def daemon_base_url(metadata: dict[str, Any] | None = None) -> str:
    meta = metadata or read_daemon_metadata()
    if not meta:
        config = get_gateway_config()
        return f"http://{config.daemon.host}:{config.daemon.port}"
    return f"http://{meta['host']}:{meta['port']}"


def daemon_http_get(path: str, *, timeout_sec: float = 2.0, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request_json("GET", path, None, timeout_sec=timeout_sec, metadata=metadata)


def daemon_http_post(path: str, body: dict[str, Any], *, timeout_sec: float = 5.0, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request_json("POST", path, body, timeout_sec=timeout_sec, metadata=metadata)


def ensure_daemon_ready_for_live(*, config_file: str | Path | None = None) -> dict[str, Any]:
    metadata = read_daemon_metadata()
    if not metadata:
        raise DaemonClientError("live trading requires daemon: start it with tbot daemon start")
    requested = str(Path(config_file or DEFAULT_CONFIG_FILE))
    running = str(metadata.get("config_file") or "")
    if running and Path(running) != Path(requested):
        raise DaemonClientError(
            "daemon config mismatch: restart daemon with the same --config-file before running live commands"
        )
    try:
        return daemon_http_get("/api/daemon/status", metadata=metadata)
    except DaemonClientError as exc:
        raise DaemonClientError("live trading requires a healthy daemon: start it with tbot daemon start") from exc


def _request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    *,
    timeout_sec: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{daemon_base_url(metadata)}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        parsed_detail: Any = detail
        try:
            parsed_detail = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            parsed_detail = detail
        message = _daemon_error_message(parsed_detail) or detail or f"daemon request failed: {exc.code}"
        raise DaemonClientError(message, status_code=exc.code, detail=parsed_detail) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DaemonClientError(f"daemon request failed: {exc}") from exc


def _daemon_error_message(detail: Any) -> str | None:
    if isinstance(detail, dict):
        inner = detail.get("detail")
        if isinstance(inner, str):
            return inner
        if isinstance(inner, dict):
            if isinstance(inner.get("error"), str):
                return inner["error"]
        if isinstance(detail.get("error"), str):
            return str(detail.get("error"))
    if isinstance(detail, str):
        return detail
    return None
