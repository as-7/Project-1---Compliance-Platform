"""Prompt loader strips HTML-comment placeholders and rejects empty templates."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.services.prompts import (
    PromptNotConfiguredError,
    load_prompt,
    render_prompt,
)


def _write_prompt(name: str, body: str) -> Path:
    settings = get_settings()
    settings.prompts_dir.mkdir(parents=True, exist_ok=True)
    path = settings.prompts_dir / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_empty_placeholder_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path))
    # We can't easily override prompts_dir without rebuilding settings; instead
    # write directly to the configured prompts_dir and use a unique name.
    name = "test_loader_empty_xyz"
    _write_prompt(name, "<!-- placeholder only -->\n")
    load_prompt.cache_clear()
    with pytest.raises(PromptNotConfiguredError):
        load_prompt(name)


def test_rendering_substitutes_variables():
    name = "test_loader_render_xyz"
    _write_prompt(name, "Hello {who}! Today is {when}.")
    load_prompt.cache_clear()
    out = render_prompt(name, who="world", when="now")
    assert out == "Hello world! Today is now."


def test_rendering_missing_var_raises():
    name = "test_loader_missing_xyz"
    _write_prompt(name, "{required_var}")
    load_prompt.cache_clear()
    with pytest.raises(PromptNotConfiguredError):
        render_prompt(name)
