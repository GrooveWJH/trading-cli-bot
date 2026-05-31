from __future__ import annotations


def transfer_planning_metadata() -> dict[str, object]:
    return {
        "account_state_source": "not_used",
        "account_state_age_sec": None,
        "market_data_source": "live",
        "fallback_reason": None,
    }
