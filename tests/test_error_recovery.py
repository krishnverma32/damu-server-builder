"""Tests for Error Recovery, Rollback, and Retries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.errors import ErrorCategory, classify_error
from engines.builder.rollback import BuilderRollback
from engines.recovery.error_classifier import is_retryable
from engines.recovery.retry import with_retry
from tests.mock_discord import MockGuild, MockRole


def test_error_classification():
    assert is_retryable(discord.RateLimited(4.0)) is True
    assert is_retryable(TimeoutError()) is True

    # Forbidden and Hierarchy are not retryable
    err_resp = MagicMock()
    err_resp.status = 403
    forbidden = discord.Forbidden(err_resp, "Missing Permissions")
    assert is_retryable(forbidden) is False
    assert classify_error(forbidden) == ErrorCategory.PERMISSION


@pytest.mark.anyio
async def test_retry_on_rate_limit():
    attempts = 0

    async def flaky_op():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise discord.RateLimited(0.01)
        return "success"

    result = await with_retry(flaky_op, max_retries=3, base_delay=0.01)
    assert result == "success"
    assert attempts == 2


@pytest.mark.anyio
async def test_rollback_deletes_resources():
    guild = MockGuild()
    role = await guild.create_role(name="TestRole")
    ch = await guild.create_text_channel(name="test-ch")
    assert role in guild.roles
    assert ch in guild.channels

    rollback = BuilderRollback()
    summary = await rollback.rollback([ch], [role], build_id="TEST-BUILD")
    assert "Rolled back 1 channels and 1 roles" in summary
    assert ch not in guild.channels
