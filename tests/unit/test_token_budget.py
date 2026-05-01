"""Token-budget guard."""
from __future__ import annotations

import pytest

from app.services.token_budget import TokenBudget, TokenBudgetExceeded


@pytest.mark.asyncio
async def test_per_request_cap_enforced(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_BUDGET_PER_REQUEST", "1000")
    monkeypatch.setenv("LLM_TOKEN_BUDGET_PER_DAY", "10000")
    # Reload settings via lru_cache reset
    from app.config import get_settings

    get_settings.cache_clear()
    budget = TokenBudget()
    with pytest.raises(TokenBudgetExceeded):
        await budget.check_request(requested_input=2000)


@pytest.mark.asyncio
async def test_daily_cap_enforced(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_BUDGET_PER_REQUEST", "100000")
    monkeypatch.setenv("LLM_TOKEN_BUDGET_PER_DAY", "150")

    from app.config import get_settings

    get_settings.cache_clear()
    budget = TokenBudget()
    await budget.record(provider="anthropic", input_tokens=80, output_tokens=20)
    with pytest.raises(TokenBudgetExceeded):
        await budget.record(provider="anthropic", input_tokens=80, output_tokens=20)
    snap = budget.snapshot()
    assert snap["by_provider"]["anthropic"] >= 100
