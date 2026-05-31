from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, List

from trading_gateway.support.redaction import redact_mapping, redact_text

JobFn = Callable[[Callable[[dict[str, Any]], None]], dict[str, Any]]


class JobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live_job: str | None = None
        self._jobs: dict[str, dict[str, Any]] = {}

    def start(self, kind: str, fn: JobFn, *, live: bool, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if live and self._live_job:
                return {"error": "live_job_running", "job_id": self._live_job}
            job_id = f"asweb_{uuid.uuid4().hex[:18]}"
            self._jobs[job_id] = _new_job(job_id, kind, live, meta=meta)
            if live:
                self._live_job = job_id
        thread = threading.Thread(target=self._run, args=(job_id, fn), name=f"tg-web-{job_id}", daemon=True)
        thread.start()
        return {"job_id": job_id, "status": "running"}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return redact_mapping(dict(job)) if job else None

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._live_job:
                return None
            job = self._jobs.get(self._live_job)
            return redact_mapping(dict(job)) if job else {"job_id": self._live_job}

    def list(self, *, limit: int = 20) -> List[dict[str, Any]]:
        with self._lock:
            rows = sorted(
                self._jobs.values(),
                key=lambda row: (str(row.get("updated_at") or ""), str(row.get("created_at") or "")),
                reverse=True,
            )
            return [redact_mapping(dict(row)) for row in rows[:limit]]

    def _run(self, job_id: str, fn: JobFn) -> None:
        def progress(step: dict[str, Any]) -> None:
            with self._lock:
                job = self._jobs[job_id]
                job["steps"].append(redact_mapping(step))
                job["updated_at"] = _now()

        try:
            result = fn(progress)
            status = "completed"
            final_status = result.get("final_status") or result.get("status")
            updates = {"status": status, "result": redact_mapping(result), "final_status": final_status}
        except Exception as exc:  # noqa: BLE001 - live jobs must become inspectable reports.
            updates = {"status": "error", "error": redact_text(exc)}
        with self._lock:
            self._jobs[job_id].update(updates)
            self._jobs[job_id]["updated_at"] = _now()
            if self._live_job == job_id:
                self._live_job = None


def _new_job(job_id: str, kind: str, live: bool, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _now()
    return {
        "job_id": job_id,
        "kind": kind,
        "live": live,
        "meta": meta or {},
        "status": "running",
        "steps": [],
        "created_at": now,
        "updated_at": now,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()
