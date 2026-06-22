"""Evolution pass budget tracking ($5 cap per curator run)."""
from __future__ import annotations

from dataclasses import dataclass, field

PASS_BUDGET_USD = 5.0
HAIKU_SWITCH_FRACTION = 0.7

# USD per 1M tokens (conservative estimates)
_MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_FALLBACK_CALL_USD = 0.25


@dataclass
class BudgetTracker:
    cap_usd: float = PASS_BUDGET_USD
    spend_usd: float = 0.0
    calls: int = 0
    model_fallbacks: int = 0
    _records: list[dict] = field(default_factory=list)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.spend_usd)

    def should_use_haiku(self) -> bool:
        return self.spend_usd >= self.cap_usd * HAIKU_SWITCH_FRACTION

    def can_afford_next_call(self) -> bool:
        return self.remaining_usd > 0.0

    def estimate_cost(
        self,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> float:
        if input_tokens is None and output_tokens is None:
            return _FALLBACK_CALL_USD
        inp = input_tokens or 0
        out = output_tokens or 0
        rates = _MODEL_RATES.get(model)
        if not rates:
            for key, val in _MODEL_RATES.items():
                if key.split("-")[1] in model:
                    rates = val
                    break
        if not rates:
            return _FALLBACK_CALL_USD
        in_rate, out_rate = rates
        return (inp * in_rate + out * out_rate) / 1_000_000

    def record_usage(
        self,
        model: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> float:
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        self.spend_usd += cost
        self.calls += 1
        self._records.append({
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 4),
        })
        return cost

    def note_haiku_fallback(self) -> None:
        self.model_fallbacks += 1

    def summary(self) -> dict:
        return {
            "cap_usd": self.cap_usd,
            "spend_usd": round(self.spend_usd, 4),
            "remaining_usd": round(self.remaining_usd, 4),
            "calls": self.calls,
            "model_fallbacks": self.model_fallbacks,
            "records": list(self._records),
        }
