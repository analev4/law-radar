"""Token accounting and an estimated spend, printed at the end of each run.

Prices are USD per million tokens from https://platform.claude.com/docs/en/about-claude/pricing,
checked on PRICE_TABLE_DATE. They are an estimate: the invoice is the source of truth.
"""
from __future__ import annotations

from typing import Dict, Tuple

from .models import Cost, ModelUsage

PRICE_TABLE_DATE = "2026-09-24"
PRICES: Dict[str, Tuple[float, float]] = {       # (input, output) per million tokens
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
CACHE_WRITE = 1.25       # x input price, 5-minute cache
CACHE_READ = 0.10        # x input price


class CostTracker:
    def __init__(self) -> None:
        self.by_model: Dict[str, ModelUsage] = {}

    def add(self, model: str, usage: Dict[str, int]) -> None:
        u = self.by_model.setdefault(model, ModelUsage())
        u.input_tokens += usage.get("input_tokens") or 0
        u.output_tokens += usage.get("output_tokens") or 0
        u.cache_creation_input_tokens += usage.get("cache_creation_input_tokens") or 0
        u.cache_read_input_tokens += usage.get("cache_read_input_tokens") or 0

    def estimated_usd(self) -> float:
        total = 0.0
        for model, u in self.by_model.items():
            inp, out = PRICES.get(model, (0.0, 0.0))
            total += (u.input_tokens * inp
                      + u.cache_creation_input_tokens * inp * CACHE_WRITE
                      + u.cache_read_input_tokens * inp * CACHE_READ
                      + u.output_tokens * out) / 1_000_000
        return round(total, 4)

    def to_model(self) -> Cost:
        return Cost(by_model=dict(self.by_model), estimated_usd=self.estimated_usd(),
                    price_table_date=PRICE_TABLE_DATE)

    def summary(self) -> str:
        if not self.by_model:
            return "Model calls: none. Estimated spend: $0.00"
        lines = []
        for model, u in self.by_model.items():
            lines.append(f"  {model}: {u.input_tokens:,} in (+{u.cache_read_input_tokens:,} cached, "
                         f"+{u.cache_creation_input_tokens:,} cache writes), {u.output_tokens:,} out")
        return "Model usage:\n" + "\n".join(lines) + f"\nEstimated spend: ${self.estimated_usd():.2f} " \
               f"(prices as of {PRICE_TABLE_DATE})"
