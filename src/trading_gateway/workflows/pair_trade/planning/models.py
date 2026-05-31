from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PairFinalStatus(StrEnum):
    TARGET_REACHED = "pair_target_reached"
    TARGET_NOT_REACHED = "pair_target_not_reached"
    UNHEDGED_RESCUE_FAILED = "pair_unhedged_rescue_failed"
    IMBALANCED = "pair_imbalanced"
    BLOCKED = "blocked"
    SUBMIT_ERROR = "submit_error"
    ORDER_STATE_UNKNOWN = "order_state_unknown"


@dataclass(frozen=True)
class PairSidePlan:
    current_quantity: float
    target_quantity: float
    best_bid: float | None = None
    best_ask: float | None = None
    estimated_quote_usdt: float | None = None
    estimated_notional_usdt: float | None = None

    @classmethod
    def spot_from(cls, payload: dict[str, Any]) -> "PairSidePlan":
        return cls(
            float(payload["current_quantity"]),
            float(payload["target_quantity"]),
            _optional_float(payload.get("best_bid")),
            _optional_float(payload.get("best_ask")),
            _optional_float(payload.get("estimated_quote_usdt")),
        )

    @classmethod
    def perp_from(cls, payload: dict[str, Any]) -> "PairSidePlan":
        return cls(float(payload["current_short_quantity"]), float(payload["target_short_quantity"]), estimated_notional_usdt=_optional_float(payload.get("estimated_notional_usdt")))


@dataclass(frozen=True)
class PairPlan:
    raw: dict[str, Any]
    spot_exchange: str
    perp_exchange: str
    canonical_symbol: str
    symbol: str
    perp_symbol: str
    spot_native_symbol: str
    perp_native_symbol: str
    base_asset: str
    quote_asset: str
    perp_contract_size: float
    target_delta_quantity: float
    quantity_step: float
    reference_price: float
    confirm_phrase: str
    can_execute: bool
    intent: str
    spot: PairSidePlan
    perp: PairSidePlan

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PairPlan":
        _require_keys(
            payload,
            (
                "spot_exchange",
                "perp_exchange",
                "canonical_symbol",
                "symbol",
                "perp_symbol",
                "spot_native_symbol",
                "perp_native_symbol",
                "base_asset",
                "quote_asset",
                "perp_contract_size",
                "target_delta_quantity",
                "quantity_step",
                "reference_price",
                "confirm_phrase",
                "can_execute",
                "intent",
                "spot",
                "perp",
            ),
        )
        if not isinstance(payload["spot"], dict) or not isinstance(payload["perp"], dict):
            raise ValueError("pair plan spot/perp sections must be objects")
        return cls(
            raw=dict(payload),
            spot_exchange=str(payload["spot_exchange"]),
            perp_exchange=str(payload["perp_exchange"]),
            canonical_symbol=str(payload["canonical_symbol"]),
            symbol=str(payload["symbol"]),
            perp_symbol=str(payload["perp_symbol"]),
            spot_native_symbol=str(payload["spot_native_symbol"]),
            perp_native_symbol=str(payload["perp_native_symbol"]),
            base_asset=str(payload["base_asset"]),
            quote_asset=str(payload["quote_asset"]),
            perp_contract_size=float(payload["perp_contract_size"]),
            target_delta_quantity=float(payload["target_delta_quantity"]),
            quantity_step=float(payload["quantity_step"]),
            reference_price=float(payload["reference_price"]),
            confirm_phrase=str(payload["confirm_phrase"]),
            can_execute=bool(payload["can_execute"]),
            intent=str(payload["intent"]),
            spot=PairSidePlan.spot_from(payload["spot"]),
            perp=PairSidePlan.perp_from(payload["perp"]),
        )


@dataclass(frozen=True)
class PairState:
    spot_current: float
    spot_quote_free: float
    perp_short_current: float
    perp_quote_free: float

    def to_dict(self) -> dict[str, float]:
        return {
            "spot_current": self.spot_current,
            "spot_quote_free": self.spot_quote_free,
            "perp_short_current": self.perp_short_current,
            "perp_quote_free": self.perp_quote_free,
        }


@dataclass(frozen=True)
class PairTarget:
    spot_before: float
    perp_before: float
    spot_target: float
    perp_target: float
    target_delta: float
    tolerance: float
    intent: str = "open"

    @classmethod
    def from_state(cls, state: PairState, quantity: float, tolerance: float, *, intent: str = "open") -> "PairTarget":
        if intent == "close":
            return cls(
                state.spot_current,
                state.perp_short_current,
                max(0.0, state.spot_current - quantity),
                max(0.0, state.perp_short_current - quantity),
                quantity,
                tolerance,
                intent,
            )
        return cls(state.spot_current, state.perp_short_current, state.spot_current + quantity, state.perp_short_current + quantity, quantity, tolerance, intent)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PairTarget":
        _require_keys(payload, ("spot_before", "perp_before", "spot_target", "perp_target", "target_delta", "tolerance"))
        return cls(
            spot_before=float(payload["spot_before"]),
            perp_before=float(payload["perp_before"]),
            spot_target=float(payload["spot_target"]),
            perp_target=float(payload["perp_target"]),
            target_delta=float(payload["target_delta"]),
            tolerance=float(payload["tolerance"]),
            intent=str(payload.get("intent") or "open"),
        )

    def to_dict(self) -> dict[str, float | str]:
        return {
            "spot_before": self.spot_before,
            "perp_before": self.perp_before,
            "spot_target": self.spot_target,
            "perp_target": self.perp_target,
            "target_delta": self.target_delta,
            "tolerance": self.tolerance,
            "intent": self.intent,
        }


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"missing pair plan keys: {', '.join(missing)}")


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
