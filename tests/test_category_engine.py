"""Tests for Category Engine operations."""

from __future__ import annotations

import pytest

from engines.guild.category_engine import CategoryEngine
from tests.mock_discord import MockGuild


@pytest.fixture
def cat_guild():
    return MockGuild()


@pytest.mark.anyio
async def test_create_and_rename_category(cat_guild):
    engine = CategoryEngine()
    cat = await engine.create_category(cat_guild, {"name": "Information"})
    assert cat.name == "Information"
    assert cat in cat_guild.categories

    renamed = await engine.rename_category(cat_guild, cat.id, "📢 ANNOUNCEMENTS")
    assert renamed.name == "📢 ANNOUNCEMENTS"


@pytest.mark.anyio
async def test_orphan_channel_detection(cat_guild):
    engine = CategoryEngine()
    # Create category and child channel
    cat = await engine.create_category(cat_guild, {"name": "Community"})
    await cat_guild.create_text_channel(name="general", category=cat)

    # Create orphan channel without category
    await cat_guild.create_text_channel(name="lonely-channel", category=None)

    orphans = engine.detect_orphan_channels(cat_guild)
    orphan_names = [c.name for c in orphans]
    assert "lonely-channel" in orphan_names
    assert "general" not in orphan_names
