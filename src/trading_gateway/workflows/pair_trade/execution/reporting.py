from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_gateway.adapters.exchanges.fees import fee_report
from trading_gateway.support.redaction import redact_mapping
from trading_gateway.workflows.pair_trade.journaling.journal import PairJournal
from trading_gateway.workflows.pair_trade.planning.models import PairFinalStatus, PairPlan

Progress = Callable[[dict[str, Any]], None]


def add_step(steps: list[dict[str, Any]], step: dict[str, Any], progress: Progress | None) -> None:
    if isinstance(step.get("status"), PairFinalStatus):
        step = {**step, "status": str(step["status"])}
    steps.append(step)
    if progress:
        progress(step)


def finish_execution(journal: PairJournal, plan: PairPlan, steps: list[dict[str, Any]], final_status: PairFinalStatus, target: dict[str, Any], pair_id: str) -> dict[str, Any]:
    journal.finish(final_status, target)
    return report_execution(plan, steps, final_status, target, pair_id)


def report_execution(plan: PairPlan, steps: list[dict[str, Any]], final_status: PairFinalStatus, target: dict[str, Any] | None = None, pair_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": "pair_close_run" if plan.intent == "close" else "pair_trading_run",
        "final_status": str(final_status),
        "plan": plan.raw,
        "steps": steps,
        "fees": fee_report(plan, steps),
    }
    if target is not None:
        payload["target"] = target
    if pair_id:
        payload["pair_id"] = pair_id
    return redact_mapping(payload)
