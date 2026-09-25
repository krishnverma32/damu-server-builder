"""Tests for Interaction Safety Layer."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.interaction import (
    InteractionSafety,
    interaction_alive,
    is_acknowledged,
    safe_defer,
    safe_edit,
    safe_followup,
    safe_modal,
    safe_send,
)
from tests.mock_discord import MockGuild, MockInteraction, MockMember


@pytest.fixture
def mock_inter():
    guild = MockGuild()
    user = MockMember(id=123, name="Tester", guild=guild)
    return MockInteraction(guild=guild, user=user)


@pytest.mark.anyio
async def test_interaction_not_acknowledged_initially(mock_inter):
    assert not is_acknowledged(mock_inter)
    assert interaction_alive(mock_inter)


@pytest.mark.anyio
async def test_safe_defer_success(mock_inter):
    success = await safe_defer(mock_inter, ephemeral=True)
    assert success is True
    assert is_acknowledged(mock_inter)


@pytest.mark.anyio
async def test_safe_defer_already_acknowledged(mock_inter):
    await safe_defer(mock_inter, ephemeral=True)
    assert is_acknowledged(mock_inter)
    # Second defer should return True without throwing InteractionResponded
    success2 = await safe_defer(mock_inter, ephemeral=True)
    assert success2 is True


@pytest.mark.anyio
async def test_safe_send_unacknowledged_calls_response(mock_inter):
    assert not is_acknowledged(mock_inter)
    await safe_send(mock_inter, content="Hello World", ephemeral=True)
    assert is_acknowledged(mock_inter)
    mock_inter.response.send_message.assert_called_once()
    mock_inter.followup.send.assert_not_called()


@pytest.mark.anyio
async def test_safe_send_acknowledged_calls_followup(mock_inter):
    await safe_defer(mock_inter, ephemeral=True)
    assert is_acknowledged(mock_inter)
    await safe_send(mock_inter, content="Followup message", ephemeral=True)
    mock_inter.followup.send.assert_called_once()


@pytest.mark.anyio
async def test_safe_defer_handles_10062_unknown_interaction(mock_inter):
    # Simulate Discord 10062 NotFound
    err_response = MagicMock()
    err_response.status = 404
    exc = discord.NotFound(err_response, "Unknown interaction")
    exc.code = 10062
    mock_inter.response.defer = AsyncMock(side_effect=exc)

    res = await safe_defer(mock_inter, ephemeral=True)
    assert res is False


@pytest.mark.anyio
async def test_safe_modal_blocks_if_acknowledged(mock_inter):
    await safe_defer(mock_inter, ephemeral=True)
    modal = MagicMock()
    sent = await safe_modal(mock_inter, modal)
    assert sent is False
    mock_inter.response.send_modal.assert_not_called()


@pytest.mark.anyio
async def test_safe_modal_succeeds_if_unacknowledged(mock_inter):
    modal = MagicMock()
    sent = await safe_modal(mock_inter, modal)
    assert sent is True
    mock_inter.response.send_modal.assert_called_once_with(modal)


@pytest.mark.anyio
async def test_expired_interaction_detection(mock_inter):
    # Set created_at to 20 minutes ago
    mock_inter.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)
    assert not interaction_alive(mock_inter)
    # safe_defer should recognize expired interaction
    deferred = await safe_defer(mock_inter, ephemeral=True)
    assert deferred is False
