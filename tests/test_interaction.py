"""Tests for Interaction Safety Layer and Global API Coordination."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.discord_api.guard import api_guard
from core.discord_api.state import APIState
from core.interaction import (
    InteractionResultReason,
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


@pytest.fixture(autouse=True)
def reset_guard():
    api_guard.reset()
    yield
    api_guard.reset()


@pytest.fixture
def mock_inter():
    guild = MockGuild()
    user = MockMember(id=123, name="Tester", guild=guild)
    return MockInteraction(guild=guild, user=user)


def make_mock_interaction(is_done=False):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = is_done
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.anyio
async def test_interaction_not_acknowledged_initially(mock_inter):
    assert not is_acknowledged(mock_inter)
    assert interaction_alive(mock_inter)


# ── Test 21: safe_defer success ───────────────────────────────────────────────
@pytest.mark.anyio
async def test_safe_defer_success(mock_inter):
    success = await safe_defer(mock_inter, ephemeral=True)
    assert success.success is True
    assert success.reason == InteractionResultReason.SUCCESS
    assert is_acknowledged(mock_inter)


# ── Test 25: interaction already responded ────────────────────────────────────
@pytest.mark.anyio
async def test_safe_defer_already_acknowledged(mock_inter):
    await safe_defer(mock_inter, ephemeral=True)
    assert is_acknowledged(mock_inter)
    # Second defer should return True without throwing InteractionResponded
    success2 = await safe_defer(mock_inter, ephemeral=True)
    assert success2.success is True
    assert success2.reason == InteractionResultReason.ALREADY_RESPONDED


@pytest.mark.anyio
async def test_safe_send_unacknowledged_calls_response(mock_inter):
    assert not is_acknowledged(mock_inter)
    res = await safe_send(mock_inter, content="Hello World", ephemeral=True)
    assert res.success is True
    assert is_acknowledged(mock_inter)
    mock_inter.response.send_message.assert_called_once()
    mock_inter.followup.send.assert_not_called()


@pytest.mark.anyio
async def test_safe_send_acknowledged_calls_followup(mock_inter):
    await safe_defer(mock_inter, ephemeral=True)
    assert is_acknowledged(mock_inter)
    res = await safe_send(mock_inter, content="Followup message", ephemeral=True)
    assert res.success is True
    mock_inter.followup.send.assert_called_once()


# ── Test 26: expired interaction / 10062 ──────────────────────────────────────
@pytest.mark.anyio
async def test_safe_defer_handles_10062_unknown_interaction(mock_inter):
    # Simulate Discord 10062 NotFound
    err_response = MagicMock()
    err_response.status = 404
    exc = discord.NotFound(err_response, "Unknown interaction")
    exc.code = 10062
    mock_inter.response.defer = AsyncMock(side_effect=exc)

    res = await safe_defer(mock_inter, ephemeral=True)
    assert res.success is False
    assert res.reason == InteractionResultReason.INTERACTION_EXPIRED


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
    deferred = await safe_defer(mock_inter, ephemeral=True)
    assert deferred.success is False
    assert deferred.reason == InteractionResultReason.INTERACTION_EXPIRED


# ── Test 22: safe_defer 429 ───────────────────────────────────────────────────
@pytest.mark.anyio
async def test_safe_defer_429():
    interaction = make_mock_interaction(is_done=False)
    resp = MagicMock(status=429, reason="Too Many Requests")
    http_exc = discord.HTTPException(response=resp, message='{"retry_after": 5.0}')
    http_exc.text = '{"retry_after": 5.0}'
    interaction.response.defer.side_effect = http_exc

    res = await safe_defer(interaction, ephemeral=True)
    assert res.success is False
    assert res.reason == InteractionResultReason.RATE_LIMITED
    assert res.is_blocked is True
    assert api_guard.state == APIState.RATE_LIMITED


# ── Test 23: safe_defer Cloudflare 1015 ───────────────────────────────────────
@pytest.mark.anyio
async def test_safe_defer_cloudflare_1015():
    interaction = make_mock_interaction(is_done=False)
    resp = MagicMock(status=429, reason="Too Many Requests")
    cf_html = "<html><body>Error 1015: You are being rate limited</body></html>"
    http_exc = discord.HTTPException(response=resp, message=cf_html)
    http_exc.text = cf_html
    interaction.response.defer.side_effect = http_exc

    res = await safe_defer(interaction, ephemeral=True)
    assert res.success is False
    assert res.reason == InteractionResultReason.CLOUDFLARE_BLOCKED
    assert res.is_blocked is True
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED


# ── Test 24: safe_send 429 ────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_safe_send_429():
    interaction = make_mock_interaction(is_done=False)
    resp = MagicMock(status=429, reason="Too Many Requests")
    http_exc = discord.HTTPException(response=resp, message="Rate limited")
    interaction.response.send_message.side_effect = http_exc

    res = await safe_send(interaction, content="Hello", ephemeral=True)
    assert res.success is False
    assert res.reason in (
        InteractionResultReason.RATE_LIMITED,
        InteractionResultReason.CLOUDFLARE_BLOCKED,
    )
    assert res.is_blocked is True


# ── Test 27: no duplicate fallback requests ───────────────────────────────────
@pytest.mark.anyio
async def test_no_duplicate_fallback_requests_on_defer_429():
    interaction = make_mock_interaction(is_done=False)
    resp = MagicMock(status=429, reason="Too Many Requests")
    http_exc = discord.HTTPException(response=resp, message="Rate limited")
    interaction.response.defer.side_effect = http_exc

    res = await safe_defer(interaction)
    assert res.success is False
    interaction.followup.send.assert_not_called()


# ── Test 28: no API request chain after known global block ────────────────────
@pytest.mark.anyio
async def test_no_api_requests_after_global_block():
    api_guard.record_failure(
        status=429,
        body="Error 1015",
        headers={"retry-after": "60"},
    )
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED

    interaction = make_mock_interaction(is_done=False)

    defer_res = await safe_defer(interaction)
    assert defer_res.success is False
    assert defer_res.reason == InteractionResultReason.CLOUDFLARE_BLOCKED
    interaction.response.defer.assert_not_called()

    send_res = await safe_send(interaction, content="test")
    assert send_res.success is False
    assert send_res.reason == InteractionResultReason.CLOUDFLARE_BLOCKED
    interaction.response.send_message.assert_not_called()
    interaction.followup.send.assert_not_called()
