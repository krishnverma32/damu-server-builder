"""Tests for Channel Engine operations."""

from __future__ import annotations

import discord
import pytest

from core.errors import PermissionError, ValidationError
from engines.guild.channel_engine import ChannelEngine
from tests.mock_discord import MockGuild


@pytest.fixture
def channel_guild():
    guild = MockGuild()
    return guild


@pytest.mark.anyio
async def test_create_text_channel(channel_guild):
    engine = ChannelEngine()
    params = {"name": "general-chat", "type": "text", "topic": "General discussion"}
    ch = await engine.create_channel(channel_guild, params)
    assert ch.name == "general-chat"
    assert ch.topic == "General discussion"
    assert ch in channel_guild.channels


@pytest.mark.anyio
async def test_create_voice_channel(channel_guild):
    engine = ChannelEngine()
    params = {"name": "Gaming Voice", "type": "voice", "bitrate": 64000, "user_limit": 5}
    ch = await engine.create_channel(channel_guild, params)
    assert ch.name == "Gaming Voice"
    assert ch.type == discord.ChannelType.voice
    assert ch in channel_guild.channels


@pytest.mark.anyio
async def test_create_channel_missing_permission(channel_guild):
    # Revoke bot's manage_channels permission
    channel_guild.me.roles[0].permissions = discord.Permissions.none()
    engine = ChannelEngine()
    params = {"name": "test-channel", "type": "text"}
    with pytest.raises(PermissionError):
        await engine.create_channel(channel_guild, params)


@pytest.mark.anyio
async def test_create_channel_empty_name(channel_guild):
    engine = ChannelEngine()
    params = {"name": "", "type": "text"}
    with pytest.raises(ValidationError):
        await engine.create_channel(channel_guild, params)


@pytest.mark.anyio
async def test_delete_channel(channel_guild):
    engine = ChannelEngine()
    ch = await engine.create_channel(channel_guild, {"name": "to-delete"})
    assert ch in channel_guild.channels
    deleted = await engine.delete_channel(channel_guild, {"channel_id": ch.id})
    assert deleted is True
    assert ch not in channel_guild.channels
