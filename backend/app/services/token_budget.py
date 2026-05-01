"""Tracks LLM token usage per request and per UTC day."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


class TokenBudgetExceeded(RuntimeError):
    pass


@dataclass
class _DailyCounter:
    day: str
    input_tokens: int = 0
    output_tokens: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)


class TokenBudget:
    def __init__(self) -> None:
        s = get_settings()
        self._per_request_max = s.llm_token_budget_per_request
        self._per_day_max = s.llm_token_budget_per_day
        self._daily = _DailyCounter(day=self._today())
        self._lock = asyncio.Lock()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def check_request(self, *, requested_input: int) -> None:
        if requested_input > self._per_request_max:
            raise TokenBudgetExceeded(
                f"Request would consume {requested_input} input tokens; "
                f"per-request cap is {self._per_request_max}."
            )

    async def record(
        self, *, provider: str, input_tokens: int, output_tokens: int
    ) -> None:
        async with self._lock:
            today = self._today()
            if today != self._daily.day:
                self._daily = _DailyCounter(day=today)
            self._daily.input_tokens += input_tokens
            self._daily.output_tokens += output_tokens
            self._daily.by_provider[provider] = (
                self._daily.by_provider.get(provider, 0) + input_tokens + output_tokens
            )
            total = self._daily.input_tokens + self._daily.output_tokens
            if total > self._per_day_max:
                log.warning(
                    "budget.daily_exceeded",
                    total=total,
                    cap=self._per_day_max,
                    provider=provider,
                )
                raise TokenBudgetExceeded(
                    f"Daily token cap exceeded: {total} > {self._per_day_max}"
                )

    def snapshot(self) -> dict:
        return {
            "day": self._daily.day,
            "input_tokens": self._daily.input_tokens,
            "output_tokens": self._daily.output_tokens,
            "by_provider": dict(self._daily.by_provider),
            "per_request_cap": self._per_request_max,
            "per_day_cap": self._per_day_max,
        }


_singleton: TokenBudget | None = None


def get_token_budget() -> TokenBudget:
    global _singleton
    if _singleton is None:
        _singleton = TokenBudget()
    return _singleton
