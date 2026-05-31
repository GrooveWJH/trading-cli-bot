from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .live import resume_live_execution, run_live_execution

Progress = Callable[[dict[str, Any]], None]


def run_close_execution(
    spot_client: Any,
    perp_client: Any,
    plan: dict[str, Any],
    *,
    confirm: str,
    timeout_sec: float | None = None,
    normal_max_requotes: int | None = None,
    recovery_max_requotes: int | None = None,
    poll_interval_sec: float | None = None,
    journal_dir: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    return run_live_execution(
        spot_client,
        perp_client,
        plan,
        confirm=confirm,
        timeout_sec=timeout_sec,
        normal_max_requotes=normal_max_requotes,
        recovery_max_requotes=recovery_max_requotes,
        poll_interval_sec=poll_interval_sec,
        journal_dir=journal_dir,
        progress=progress,
    )


def resume_close_execution(
    spot_client: Any,
    perp_client: Any,
    pair_id: str,
    *,
    confirm: str,
    timeout_sec: float | None = None,
    normal_max_requotes: int | None = None,
    journal_dir: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    return resume_live_execution(
        spot_client,
        perp_client,
        pair_id,
        confirm=confirm,
        timeout_sec=timeout_sec,
        normal_max_requotes=normal_max_requotes,
        journal_dir=journal_dir,
        progress=progress,
    )
