from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable
from typing import Protocol, cast

import typer

from trading_gateway.interfaces.daemon.client import clear_daemon_runtime_files, read_daemon_metadata, write_daemon_metadata, write_daemon_pid
from trading_gateway.interfaces.daemon.runtime import DaemonRuntime, get_daemon_runtime, stop_daemon_runtime
from trading_gateway.interfaces.daemon.serve import main as serve_daemon
from trading_gateway.app.config import get_gateway_config


class _RuntimeStatusProvider(Protocol):
    def status_payload(self) -> dict[str, object]: ...


def start_daemon() -> None:
    config = get_gateway_config()
    existing = read_daemon_metadata()
    if existing and _pid_alive(int(existing.get("pid") or 0)):
        raise typer.BadParameter("daemon is already running; use tbot daemon status", param_hint="daemon")
    clear_daemon_runtime_files()
    payload = {
        "pid": os.getpid(),
        "host": config.daemon.host,
        "port": config.daemon.port,
        "started_at": time.time(),
        "config_file": str(config.path),
    }
    write_daemon_metadata(payload)
    write_daemon_pid(os.getpid())
    typer.echo(f"Trading Gateway daemon starting on http://{config.daemon.host}:{config.daemon.port}")
    typer.echo("Running in foreground. Press Ctrl+C to stop.")
    runtime = get_daemon_runtime()
    watch_stop = _start_route_watch(runtime)
    try:
        serve_daemon(host=config.daemon.host, port=config.daemon.port)
    finally:
        watch_stop.set()
        stop_daemon_runtime()
        clear_daemon_runtime_files()


def stop_daemon() -> None:
    metadata = read_daemon_metadata()
    if not metadata:
        typer.echo("Trading Gateway daemon is not running")
        return
    pid = int(metadata.get("pid") or 0)
    if pid and _pid_alive(pid):
        try:
            from trading_gateway.interfaces.daemon.client import daemon_http_post

            daemon_http_post("/api/daemon/stop", {}, metadata=metadata)
            time.sleep(0.2)
        except Exception:  # noqa: BLE001
            pass
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    clear_daemon_runtime_files()
    typer.echo("Trading Gateway daemon stopped")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _start_route_watch(runtime: DaemonRuntime) -> threading.Event:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_watch_route_health,
        args=(runtime, stop_event, lambda line: typer.echo(line, err=True)),
        kwargs={"poll_sec": 0.5},
        name="tg-daemon-watch",
        daemon=True,
    )
    thread.start()
    return stop_event


def _watch_route_health(
    runtime: _RuntimeStatusProvider,
    stop_event: threading.Event,
    printer: Callable[[str], None],
    *,
    poll_sec: float,
) -> None:
    last_overall: str | None = None
    last_routes: dict[str, tuple[str | None, str | None]] = {}
    while not stop_event.is_set():
        payload = runtime.status_payload()
        overall = str(payload.get("status") or "")
        if overall and overall != last_overall:
            printer(f"[daemon] overall -> {overall}")
            last_overall = overall
        raw_routes = payload.get("routes")
        routes = raw_routes if isinstance(raw_routes, list) else []
        for row in routes:
            if not isinstance(row, dict):
                continue
            row_map = cast(dict[str, object], row)
            route = str(row_map.get("route") or "")
            status = str(row_map.get("status") or "")
            error = row_map.get("last_error")
            current = (status or None, str(error) if error not in (None, "") else None)
            previous = last_routes.get(route)
            if route and current != previous:
                message = f"[daemon] {route} -> {status}"
                if current[1]:
                    message += f" error={current[1]}"
                printer(message)
                last_routes[route] = current
        stop_event.wait(poll_sec)
