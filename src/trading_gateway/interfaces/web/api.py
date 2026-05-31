from __future__ import annotations

from typing import Any, Callable

from trading_gateway.interfaces.daemon.client import DaemonClientError, daemon_http_get, daemon_http_post
from trading_gateway.interfaces.daemon.runtime import get_daemon_runtime
from trading_gateway.interfaces.web import ops
from trading_gateway.interfaces.web.jobs import JobRegistry
from trading_gateway.interfaces.web.runtime import binance_universe, recent_pair_journals, static_dir, status_payload
from trading_gateway.support.redaction import redact_text

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
def create_app() -> Any:
    return create_daemon_app()


def create_daemon_app() -> Any:
    app, registry = _base_app("Trading Gateway Daemon")
    _register_read_routes(app, include_pair_routes=True)
    _register_daemon_routes(app, registry)
    _mount_static(app)
    return app
def create_web_app() -> Any:
    app, registry = _base_app("Trading Gateway Web")
    _register_read_routes(app, include_pair_routes=False)
    _register_proxy_live_routes(app, registry)
    _mount_static(app)
    return app
def _api_pair_routes(app: Any, *, proxy: bool) -> None:
    from fastapi import Body

    if proxy:
        @app.post("/api/pair/plan")
        def api_pair_plan_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            return _daemon_post("/api/pair/plan", body)

        @app.post("/api/pair/close/plan")
        def api_pair_close_plan_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            return _daemon_post("/api/pair/close/plan", body)

        @app.post("/api/pair/run")
        def api_pair_run_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            return _daemon_post("/api/pair/run", body)

        @app.post("/api/pair/close/run")
        def api_pair_close_run_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
            return _daemon_post("/api/pair/close/run", body)
        return

    @app.post("/api/pair/plan")
    def api_pair_plan(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _call(lambda: ops.pair_plan(body))

    @app.post("/api/pair/close/plan")
    def api_pair_close_plan(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _call(lambda: ops.pair_close_plan(body))

    @app.post("/api/pair/run")
    def api_pair_run(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _start_live_job(getattr(app.state, "registry"), "pair_run", body, ops.pair_run)

    @app.post("/api/pair/close/run")
    def api_pair_close_run(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _start_live_job(getattr(app.state, "registry"), "pair_close_run", body, ops.pair_close_run)

def _base_app(title: str) -> tuple[Any, JobRegistry]:
    try:
        from fastapi import FastAPI, HTTPException, Request
    except ModuleNotFoundError as exc:
        raise RuntimeError("Trading Gateway web requires fastapi and uvicorn. Run: bash scripts/dev/setup.sh") from exc

    registry = JobRegistry()
    app = FastAPI(title=title, version="1.0.0")
    app.state.registry = registry

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        host = request.client.host if request.client else ""
        if host not in LOCAL_HOSTS:
            raise HTTPException(status_code=403, detail="Trading Gateway web is localhost-only")
        return await call_next(request)

    @app.get("/")
    def index() -> Any:
        from fastapi.responses import FileResponse

        return FileResponse(static_dir() / "index.html")

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return status_payload(registry.active())

    return app, registry

def _register_read_routes(app: Any, *, include_pair_routes: bool) -> None:
    from fastapi import Body

    @app.get("/api/summary")
    def api_summary() -> dict[str, Any]:
        return _call(ops.summary)

    @app.get("/api/snapshot")
    def api_snapshot() -> dict[str, Any]:
        return _call(ops.snapshot)

    @app.get("/api/orders")
    def api_orders(exchange: str, market: str, symbol: str) -> dict[str, Any]:
        return _call(lambda: ops.orders(exchange, market, symbol))

    @app.post("/api/transfer/plan")
    def api_transfer_plan(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _call(lambda: ops.transfer_plan(body))

    @app.get("/api/binance/universe")
    def api_universe() -> dict[str, Any]:
        return _call(binance_universe)

    if include_pair_routes:
        _api_pair_routes(app, proxy=False)

    @app.get("/api/pair/status/{pair_id}")
    def api_pair_status(pair_id: str) -> dict[str, Any]:
        return _call(lambda: ops.pair_status(pair_id))

    @app.get("/api/pair/close/status/{pair_id}")
    def api_pair_close_status(pair_id: str) -> dict[str, Any]:
        return _call(lambda: ops.pair_status(pair_id))

    @app.get("/api/journals")
    def api_journals() -> dict[str, Any]:
        return {"journals": recent_pair_journals()}

    @app.post("/api/lab/plan")
    def api_lab_plan(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _call(lambda: ops.lab_plan(body))

def _register_daemon_routes(app: Any, registry: JobRegistry) -> None:
    from fastapi import Body, HTTPException

    @app.get("/api/daemon/status")
    def api_daemon_status() -> dict[str, Any]:
        runtime = get_daemon_runtime()
        active = registry.active()
        runtime.set_active_job(active)
        return runtime.status_payload()

    @app.post("/api/daemon/stop")
    def api_daemon_stop() -> dict[str, Any]:
        raise SystemExit(0)

    @app.post("/api/transfer/run")
    def api_transfer_run(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _run_transfer_or_job(registry, body)

    @app.post("/api/lab/run")
    def api_lab_run(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _start_live_job(registry, "lab_run", body, ops.lab_run)

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str) -> dict[str, Any]:
        job = registry.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/api/jobs")
    def api_jobs(limit: int = 20) -> dict[str, Any]:
        return {"jobs": registry.list(limit=max(1, min(limit, 100)))}

def _register_proxy_live_routes(app: Any, registry: JobRegistry) -> None:
    from fastapi import Body

    @app.post("/api/transfer/plan")
    def api_transfer_plan_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _daemon_post("/api/transfer/plan", body)

    _api_pair_routes(app, proxy=True)

    @app.post("/api/lab/plan")
    def api_lab_plan_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _daemon_post("/api/lab/plan", body)

    @app.get("/api/daemon/status")
    def api_daemon_status_proxy() -> dict[str, Any]:
        active = registry.active()
        payload = _daemon_get("/api/daemon/status")
        if active:
            payload["active_web_job"] = active
        return payload

    @app.post("/api/transfer/run")
    def api_transfer_run_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _daemon_post("/api/transfer/run", body)

    @app.post("/api/lab/run")
    def api_lab_run_proxy(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        return _daemon_post("/api/lab/run", body)

    @app.get("/api/jobs/{job_id}")
    def api_job_proxy(job_id: str) -> dict[str, Any]:
        return _daemon_get(f"/api/jobs/{job_id}")

    @app.get("/api/jobs")
    def api_jobs_proxy(limit: int = 20) -> dict[str, Any]:
        return _daemon_get(f"/api/jobs?limit={max(1, min(limit, 100))}")

def _mount_static(app: Any) -> None:
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=static_dir()), name="static")

def _call(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - HTTP edge returns redacted user-readable errors.
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=redact_text(exc)) from exc

def _start_live_job(registry: JobRegistry, kind: str, body: dict[str, Any], fn: Any) -> dict[str, Any]:
    result = registry.start(kind, lambda progress: fn(body, progress), live=True, meta=_job_meta(kind, body))
    if result.get("error") == "live_job_running":
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=result)  # noqa: B904
    return result

def _run_transfer_or_job(registry: JobRegistry, body: dict[str, Any]) -> dict[str, Any]:
    if not bool(body.get("live")):
        return _call(lambda: ops.transfer_run(body))
    result = registry.start("transfer", lambda _progress: ops.transfer_run(body), live=True, meta=_job_meta("transfer", body))
    if result.get("error") == "live_job_running":
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail=result)  # noqa: B904
    return result

def _job_meta(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    if kind == "lab_run":
        return {"exchange": body.get("exchange"), "market": body.get("market")}
    if kind in {"pair_run", "pair_close_run"}:
        return {"spot_exchange": body.get("spot_exchange", "binance"), "perp_exchange": body.get("perp_exchange", "binance")}
    if kind == "transfer":
        return {"exchange": body.get("exchange"), "market": "spot"}
    return {}

def _daemon_get(path: str) -> dict[str, Any]:
    try:
        return daemon_http_get(path)
    except DaemonClientError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=exc.status_code or 503, detail=exc.detail or str(exc)) from exc

def _daemon_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return daemon_http_post(path, body)
    except DaemonClientError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=exc.status_code or 503, detail=exc.detail or str(exc)) from exc
