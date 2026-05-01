"""Pytest fixtures.

Many tests don't need the full docker stack — they exercise the chunker, gap
analyzer scoring math, and FastAPI routes against a SQLite in-memory DB.
Tests that require Postgres/Chroma/network are marked with `@pytest.mark.live`
and skipped unless RUN_LIVE=1.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Use SQLite for default unit/API tests; live tests override via env.
os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///:memory:?cache=shared&uri=true"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("GEMINI_API_KEY", "")


def pytest_collection_modifyitems(config, items):  # noqa: D401
    if os.environ.get("RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="set RUN_LIVE=1 to run integration tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
