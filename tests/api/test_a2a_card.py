"""A2A: Agent Card surface is correctly shaped."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_agent_card_structure():
    from app.api.routes.a2a import agent_card

    card = await agent_card()
    assert card["name"] == "extraction-agent"
    assert "endpoints" in card
    assert "skills" in card
    assert any(s["id"] == "extract_controls_from_document" for s in card["skills"])
    assert "application/pdf" in card["skills"][0]["inputModes"]
