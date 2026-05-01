"""Load externalized prompt templates from the /prompts directory."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config import get_settings


class PromptNotConfiguredError(RuntimeError):
    pass


def _strip_html_comments(text: str) -> str:
    """Strip HTML-style comments used as candidate-authoring placeholders."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("<!--", i):
            close = text.find("-->", i + 4)
            if close == -1:
                break
            i = close + 3
        else:
            out.append(text[i])
            i += 1
    return "".join(out).strip()


@lru_cache
def load_prompt(name: str) -> str:
    """Load a prompt file by stem (e.g. 'qa_agent.system')."""
    settings = get_settings()
    path: Path = settings.prompts_dir / f"{name}.md"
    if not path.exists():
        raise PromptNotConfiguredError(f"Prompt file missing: {path}")
    raw = path.read_text(encoding="utf-8")
    body = _strip_html_comments(raw)
    if not body:
        raise PromptNotConfiguredError(
            f"Prompt {path} is empty. Per the project brief, prompts must be "
            "candidate-authored. Fill it in before starting the agent."
        )
    return body


def render_prompt(name: str, **vars: object) -> str:
    """Load and substitute Python str.format-style variables."""
    template = load_prompt(name)
    try:
        return template.format(**vars)
    except KeyError as exc:
        raise PromptNotConfiguredError(
            f"Prompt {name} references undefined variable {exc!s}"
        ) from exc
