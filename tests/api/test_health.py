"""Smoke test for /health (live) — skipped without RUN_LIVE=1."""
from __future__ import annotations

import pytest


@pytest.mark.live
@pytest.mark.asyncio
async def test_health_live():
    import httpx

    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8080/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
