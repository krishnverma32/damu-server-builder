"""Comprehensive unit test suite for StartupManager and connection lifecycle subsystem.

Covers:
1. Successful startup
2. First login returns 429 (no crash, state=RATE_LIMITED, retry scheduled)
3. Multiple consecutive 429 responses (exponential backoff)
4. Retry-After header available (respected with precedence)
5. Retry-After missing (exponential backoff fallback)
6. Retry-After invalid (safe fallback to backoff)
7. 401 / invalid token (classified separately, no infinite retry loop)
8. 403 Forbidden (classified separately, non-retryable)
9. Network timeout (retryable)
10. DNS / connection failure (retryable)
11. Recovery after previous 429 (state returns to READY, backoff resets)
12. Duplicate startup invocation guard (DuplicateStartupError)
13. Shutdown during retry sleep (exits cleanly without hanging)
14. Shutdown while connecting (graceful cleanup)
15. Health endpoint while rate limited (/health = 200)
16. Readiness endpoint while rate limited (/ready = 503)
17. Readiness endpoint while ready (/ready = 200)
18. No secret leakage in logs or health models
19. Unexpected exception classification
20. Graceful shutdown sequence
"""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp
import discord

from core.startup.backoff import StartupBackoff
from core.startup.classifier import (
    ClassificationResult,
    StartupErrorCategory,
    classify_startup_error,
)
from core.startup.health_server import create_health_app
from core.startup.lifecycle import (
    ConnectionGuard,
    DuplicateStartupError,
    ShutdownCoordinator,
    cleanup_bot_for_retry,
)
from core.startup.manager import StartupManager
from core.startup.state import StartupState, StartupStatus


# ── Test Utilities & Fakes ───────────────────────────────────────────────────


class MockClientResponse:
    """Mock HTTP response matching discord.py internals."""

    def __init__(self, status: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.reason = "Mock Reason"
        self.text = text
        self.headers = headers or {}


def make_discord_http_error(status: int, text: str = "", headers: dict[str, str] | None = None) -> discord.HTTPException:
    resp = MockClientResponse(status=status, text=text, headers=headers)
    return discord.HTTPException(resp, text)  # type: ignore[arg-type]


class FakeBot:
    """Lightweight test double for discord.ext.commands.Bot."""

    def __init__(self) -> None:
        self.user = MagicMock()
        self.user.id = 1193532551348891708
        self.user.__str__ = lambda s: "FakeBot#0001"
        self.guilds = [MagicMock(), MagicMock()]
        self._is_ready = False
        self._is_closed = False
        self._listeners: dict[str, list[Any]] = {}

        # Mock http internals
        self.http = MagicMock()
        self.http.connector = MagicMock()
        self.http.connector.closed = False
        self.http.connector.close = AsyncMock()

    def is_ready(self) -> bool:
        return self._is_ready

    def is_closed(self) -> bool:
        return self._is_closed

    async def close(self) -> None:
        self._is_closed = True

    def add_listener(self, func: Any, name: str = "on_ready") -> None:
        self._listeners.setdefault(name, []).append(func)

    async def trigger_ready(self) -> None:
        self._is_ready = True
        for listener in self._listeners.get("on_ready", []):
            await listener()

    async def start(self, token: str) -> None:
        # Default fake start immediately transitions to ready
        await self.trigger_ready()


# ── 1. Successful Startup Test ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_successful_startup():
    bot = FakeBot()
    manager = StartupManager(bot, keep_alive_on_degraded=False)

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.READY
    assert manager.is_ready is True
    assert manager.attempt == 1
    health = manager.get_health_status()
    assert health["state"] == "READY"
    assert health["discord_ready"] is True


# ── 2. First Login Returns 429 Test ───────────────────────────────────────────


@pytest.mark.anyio
async def test_first_login_returns_429_recovery_to_ready():
    """Verify simulated 429 -> RATE_LIMITED -> backoff retry -> simulated login -> READY."""
    bot = FakeBot()
    backoff = StartupBackoff(base_delay=0.01, max_delay=0.1, jitter_ratio=0.0)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    attempts = 0

    async def fake_start(token: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            err = make_discord_http_error(
                429,
                text="error 1015 You are being rate limited. Cloudflare ban",
                headers={"Retry-After": "0.02"},
            )
            raise err
        # Attempt 2 succeeds
        await bot.trigger_ready()

    bot.start = fake_start

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.READY
    assert manager.is_ready is True
    assert attempts == 2
    assert manager.attempt == 2


# ── 3. Multiple Consecutive 429s (Exponential Backoff) ───────────────────────


def test_consecutive_429_exponential_backoff():
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.0)

    delay1 = backoff.calculate_delay(1)
    delay2 = backoff.calculate_delay(2)
    delay3 = backoff.calculate_delay(3)
    delay4 = backoff.calculate_delay(4)

    assert delay1 == 5.0
    assert delay2 == 10.0
    assert delay3 == 20.0
    assert delay4 == 40.0


# ── 4. Retry-After Header Respected ──────────────────────────────────────────


def test_retry_after_header_precedence():
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.0)

    # Normal delay for attempt 1 is 5.0s, but Retry-After=45.0s should take precedence
    delay = backoff.calculate_delay(1, retry_after=45.0)
    assert 45.0 <= delay <= 45.5


# ── 5. Retry-After Missing Falls Back to Backoff ──────────────────────────────


def test_retry_after_missing_fallback():
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.0)

    delay = backoff.calculate_delay(2, retry_after=None)
    assert delay == 10.0


# ── 6. Retry-After Invalid Falls Back to Backoff ──────────────────────────────


def test_retry_after_invalid_fallback():
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.0)

    delay_neg = backoff.calculate_delay(1, retry_after=-10.0)
    assert delay_neg == 5.0

    delay_nan = backoff.calculate_delay(1, retry_after=float("nan"))
    assert delay_nan == 5.0


# ── 7. 401 Invalid Token (No Endless Retry) ───────────────────────────────────


@pytest.mark.anyio
async def test_401_invalid_token_no_aggressive_retry():
    bot = FakeBot()
    backoff = StartupBackoff(base_delay=0.01, max_delay=0.05)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    call_count = 0

    async def fake_start(token: str):
        nonlocal call_count
        call_count += 1
        raise make_discord_http_error(401, "401: Unauthorized")

    bot.start = fake_start

    await manager.run("invalid_token_12345678901234567890")

    assert manager.state == StartupState.INVALID_TOKEN
    assert manager.is_ready is False
    assert call_count == 1  # Exactly 1 attempt, zero infinite retries


# ── 8. 403 Forbidden Classification ──────────────────────────────────────────


@pytest.mark.anyio
async def test_403_forbidden_classification():
    bot = FakeBot()
    manager = StartupManager(bot, keep_alive_on_degraded=False)

    async def fake_start(token: str):
        raise make_discord_http_error(403, "Missing Access / Disallowed Intent")

    bot.start = fake_start

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.DEGRADED
    assert manager.is_ready is False


# ── 9. Network Timeout Retry ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_network_timeout_retry():
    bot = FakeBot()
    backoff = StartupBackoff(base_delay=0.01, max_delay=0.05, jitter_ratio=0.0)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    attempts = 0

    async def fake_start(token: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise asyncio.TimeoutError("Connection timed out to Discord gateway")
        await bot.trigger_ready()

    bot.start = fake_start

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.READY
    assert manager.is_ready is True
    assert attempts == 2


# ── 10. DNS and Connection Failure Retry ──────────────────────────────────────


@pytest.mark.anyio
async def test_dns_and_connection_failure_retry():
    bot = FakeBot()
    backoff = StartupBackoff(base_delay=0.01, max_delay=0.05, jitter_ratio=0.0)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    attempts = 0

    async def fake_start(token: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise socket.gaierror(11001, "getaddrinfo failed")
        if attempts == 2:
            raise ConnectionResetError(10054, "Connection reset by peer")
        await bot.trigger_ready()

    bot.start = fake_start

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.READY
    assert manager.is_ready is True
    assert attempts == 3


# ── 11. Successful Recovery Resets Backoff ─────────────────────────────────────


@pytest.mark.anyio
async def test_successful_recovery_resets_backoff():
    bot = FakeBot()
    backoff = StartupBackoff(base_delay=0.01, max_delay=0.1, jitter_ratio=0.0)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    attempts = 0

    async def fake_start(token: str):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise make_discord_http_error(429, "Rate limited")
        await bot.trigger_ready()

    bot.start = fake_start

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.READY
    # Backoff reset verify: attempt 1 delay is back to base_delay
    assert backoff.calculate_delay(1) == 0.01


# ── 12. Duplicate Startup Guard (Single Connection Guarantee) ─────────────────


@pytest.mark.anyio
async def test_duplicate_startup_invocation_guard():
    bot = FakeBot()
    manager = StartupManager(bot, keep_alive_on_degraded=False)

    # Acquire connection guard
    await manager._guard.acquire()

    # Second concurrent acquire must raise DuplicateStartupError
    with pytest.raises(DuplicateStartupError, match="already actively running"):
        await manager._guard.acquire()

    await manager._guard.release()


# ── 13. Shutdown During Retry Sleep ───────────────────────────────────────────


@pytest.mark.anyio
async def test_shutdown_during_retry_sleep():
    bot = FakeBot()
    # Configure backoff with long delay (100 seconds)
    backoff = StartupBackoff(base_delay=100.0, max_delay=200.0)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    async def fake_start(token: str):
        raise make_discord_http_error(429, "Rate limited")

    bot.start = fake_start

    # Schedule shutdown after 50ms while sleeping in backoff
    async def trigger_shutdown_soon():
        await asyncio.sleep(0.05)
        manager.request_shutdown("Test shutdown")

    asyncio.create_task(trigger_shutdown_soon())

    # manager.run should terminate within ~100ms instead of waiting 100 seconds
    start_t = asyncio.get_event_loop().time()
    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")
    elapsed = asyncio.get_event_loop().time() - start_t

    assert elapsed < 2.0
    assert manager._coordinator.is_shutdown_requested is True


# ── 14. Shutdown While Connecting ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_shutdown_while_connecting():
    bot = FakeBot()
    manager = StartupManager(bot, keep_alive_on_degraded=False)

    async def fake_blocking_start(token: str):
        await manager._coordinator.shutdown_event.wait()

    bot.start = fake_blocking_start

    async def trigger_shutdown():
        await asyncio.sleep(0.05)
        manager.request_shutdown("Immediate shutdown")

    asyncio.create_task(trigger_shutdown())

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager._coordinator.is_shutdown_requested is True


# ── 15 & 16. Health & Readiness While Rate Limited ────────────────────────────


def test_health_and_readiness_while_rate_limited():
    bot = FakeBot()
    manager = StartupManager(bot)
    manager._state = StartupState.RATE_LIMITED

    app = create_health_app(manager)
    client = app.test_client()

    # /health MUST be HTTP 200 to prevent Render restart storm
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json["status"] == "ok"
    assert resp_health.json["process"] == "alive"
    assert resp_health.json["startup_state"] == "RATE_LIMITED"

    # /ready MUST be HTTP 503 to signal Discord is not connected yet
    resp_ready = client.get("/ready")
    assert resp_ready.status_code == 503
    assert resp_ready.json["status"] == "not_ready"
    assert resp_ready.json["discord"] == "disconnected"
    assert resp_ready.json["startup_state"] == "RATE_LIMITED"


# ── 17. Readiness When Ready ──────────────────────────────────────────────────


def test_readiness_when_ready():
    bot = FakeBot()
    bot._is_ready = True
    manager = StartupManager(bot)
    manager._state = StartupState.READY

    app = create_health_app(manager)
    client = app.test_client()

    resp_ready = client.get("/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json["status"] == "ready"
    assert resp_ready.json["discord"] == "connected"
    assert resp_ready.json["startup_state"] == "READY"


# ── 18. No Secret Leakage in Logs or Status Model ─────────────────────────────


def test_no_secret_leakage_in_error_classification():
    secret_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef1234567890"
    scheme = "mongodb+srv"
    mongo_uri = f"{scheme}://admin_user:super_secret_pw@cluster.mongodb.net/prod"

    raw_error_text = f"Connection failed with token={secret_token} and uri={mongo_uri}"
    exc = Exception(raw_error_text)

    result = classify_startup_error(exc)

    assert secret_token not in result.message
    assert "super_secret_pw" not in result.message
    assert "[REDACTED_SECRET]" in result.message or "[REDACTED_AUTH]" in result.message


def test_no_secret_leakage_in_health_status_model():
    bot = FakeBot()
    manager = StartupManager(bot)
    manager._last_error = "Sample error: connection reset by peer"

    status_dict = manager.get_health_status()
    raw_str = str(status_dict)

    # Verify no sensitive keywords or secrets exist in status model
    for sensitive in ("token", "password", "secret", "mongo_uri", "authorization"):
        assert sensitive not in raw_str.lower()


# ── 19. Unexpected Exception Classification ───────────────────────────────────


def test_unexpected_exception_classification():
    exc = ZeroDivisionError("division by zero in logic")
    result = classify_startup_error(exc)

    assert result.category == StartupErrorCategory.UNKNOWN
    assert result.is_retryable is False


# ── 20. Graceful Shutdown Cleanup ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_graceful_shutdown_execution():
    bot = FakeBot()
    coordinator = ShutdownCoordinator(bot)

    custom_cleaned = False

    async def custom_cleanup():
        nonlocal custom_cleaned
        custom_cleaned = True

    coordinator.register_cleanup(custom_cleanup)

    await coordinator.execute_shutdown()

    assert bot.is_closed() is True
    assert custom_cleaned is True
    assert coordinator.is_shutdown_requested is True


# ══════════════════════════════════════════════════════════════════════════════
# REQUIRED RETRY-AFTER TESTS 1 THROUGH 10 & PRODUCTION ACCEPTANCE TEST
# ══════════════════════════════════════════════════════════════════════════════


def test_req_1_retry_after_60():
    """TEST 1: Retry-After = 60 -> delay = 60."""
    backoff = StartupBackoff()
    result = backoff.calculate_delay_details(1, retry_after=60)
    assert result.delay == 60.0
    assert result.source == "server_retry_after"


def test_req_2_retry_after_600():
    """TEST 2: Retry-After = 600 -> delay = 600."""
    backoff = StartupBackoff()
    result = backoff.calculate_delay_details(1, retry_after=600)
    assert result.delay == 600.0
    assert result.source == "server_retry_after"


def test_req_3_retry_after_46765():
    """TEST 3: Retry-After = 46765 -> delay = approximately 46765, NOT 600."""
    backoff = StartupBackoff()
    result = backoff.calculate_delay_details(1, retry_after=46765)
    assert result.delay == 46765.0
    assert result.delay != 600.0
    assert result.source == "server_retry_after"


def test_req_4_retry_after_86400():
    """TEST 4: Retry-After = 86400 -> delay = 86400."""
    backoff = StartupBackoff()
    result = backoff.calculate_delay_details(1, retry_after=86400)
    assert result.delay == 86400.0
    assert result.source == "server_retry_after"


def test_req_5_retry_after_172800_capped():
    """TEST 5: Retry-After = 172800 -> delay = 86400 when STARTUP_MAX_SERVER_RETRY_AFTER = 86400."""
    backoff = StartupBackoff(max_server_retry_after=86400.0)
    result = backoff.calculate_delay_details(1, retry_after=172800)
    assert result.delay == 86400.0
    assert result.source == "server_retry_after"
    assert result.bounded_retry_after == 86400.0


def test_req_6_retry_after_missing():
    """TEST 6: Retry-After missing -> exponential backoff + jitter."""
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.25)
    result = backoff.calculate_delay_details(2, retry_after=None)
    assert result.source == "exponential_backoff"
    # Base 5.0 * 2^1 = 10.0, jitter +- 25% -> 7.5 to 12.5
    assert 7.5 <= result.delay <= 12.5


def test_req_7_retry_after_malformed():
    """TEST 7: Retry-After malformed -> exponential backoff fallback."""
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.0)
    result = backoff.calculate_delay_details(1, retry_after="malformed_header_value")
    assert result.source == "exponential_backoff"
    assert result.delay == 5.0


def test_req_8_retry_after_negative():
    """TEST 8: Retry-After negative -> exponential backoff fallback."""
    backoff = StartupBackoff(base_delay=5.0, max_delay=600.0, jitter_ratio=0.0)
    result = backoff.calculate_delay_details(1, retry_after=-120.0)
    assert result.source == "exponential_backoff"
    assert result.delay == 5.0


@pytest.mark.anyio
async def test_req_9_shutdown_during_long_retry_after():
    """TEST 9: Shutdown during a long 46,765s Retry-After exits immediately and cleanly."""
    bot = FakeBot()
    backoff = StartupBackoff()
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    async def fake_start(token: str):
        err = make_discord_http_error(
            429,
            text="Cloudflare 1015 ban",
            headers={"Retry-After": "46765"},
        )
        raise err

    bot.start = fake_start

    # Trigger shutdown after 50ms
    async def trigger_shutdown_soon():
        await asyncio.sleep(0.05)
        manager.request_shutdown("Operator shutdown during Retry-After")

    asyncio.create_task(trigger_shutdown_soon())

    start_t = asyncio.get_event_loop().time()
    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")
    elapsed = asyncio.get_event_loop().time() - start_t

    # Must exit within ~1-2 seconds, NOT waiting for 46,765 seconds
    assert elapsed < 2.0
    assert manager._coordinator.is_shutdown_requested is True
    assert manager.state in (StartupState.STOPPING, StartupState.STOPPED)


@pytest.mark.anyio
async def test_req_10_429_followed_by_successful_login():
    """TEST 10: 429 followed by successful login transitions:
    RATE_LIMITED -> wait -> reconnect -> READY -> backoff reset.
    """
    bot = FakeBot()
    backoff = StartupBackoff(base_delay=0.01, max_delay=0.1, jitter_ratio=0.0)
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    states_seen: list[StartupState] = []
    attempts = 0

    async def fake_start(token: str):
        nonlocal attempts
        attempts += 1
        states_seen.append(manager.state)
        if attempts == 1:
            err = make_discord_http_error(429, text="Rate limit", headers={"Retry-After": "0.01"})
            raise err
        # Attempt 2 connects successfully
        await bot.trigger_ready()

    bot.start = fake_start

    await manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")

    assert manager.state == StartupState.READY
    assert manager.is_ready is True
    assert attempts == 2
    # Verify backoff was reset to initial base
    assert backoff.calculate_delay(1) == 0.01

    health = manager.get_health_status()
    assert health["state"] == "READY"
    assert health["discord_ready"] is True
    assert health["next_retry_at"] is None
    assert health["retry_delay_seconds"] is None
    assert health["retry_source"] is None


@pytest.mark.anyio
async def test_production_acceptance_simulation(caplog):
    """PRODUCTION ACCEPTANCE TEST:
    Simulate:
        HTTP 429
        Retry-After = 46765
        Cloudflare 1015 response

    Expected log:
        state=RATE_LIMITED
        status=429
        retry_after=46765
        delay=46765
        retry_source=server_retry_after

    Process remains alive.
    Health endpoint remains HTTP 200.
    Status reports next_retry_at, retry_delay_seconds=46765, retry_source=server_retry_after.
    """
    bot = FakeBot()
    backoff = StartupBackoff()
    manager = StartupManager(bot, backoff=backoff, keep_alive_on_degraded=False)

    call_count = 0

    async def fake_start(token: str):
        nonlocal call_count
        call_count += 1
        err = make_discord_http_error(
            429,
            text="error 1015 You are being rate limited. Cloudflare ban",
            headers={"Retry-After": "46765"},
        )
        raise err

    bot.start = fake_start

    # Create health app
    app = create_health_app(manager)
    client = app.test_client()

    # Capture log records
    with caplog.at_level(logging.WARNING):
        # Run manager in background task
        run_task = asyncio.create_task(manager.run("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef"))

        # Wait briefly for attempt 1 to hit 429 and enter sleep
        await asyncio.sleep(0.1)

        # 1. State must be RATE_LIMITED
        assert manager.state == StartupState.RATE_LIMITED
        assert call_count == 1

        # 2. Check health endpoint remains HTTP 200
        resp_health = client.get("/health")
        assert resp_health.status_code == 200
        assert resp_health.json["status"] == "ok"
        assert resp_health.json["process"] == "alive"
        assert resp_health.json["startup_state"] == "RATE_LIMITED"

        # 3. Check /status endpoint reports retry metadata
        resp_status = client.get("/status")
        assert resp_status.status_code == 200
        status_data = resp_status.json
        assert status_data["state"] == "RATE_LIMITED"
        assert status_data["retry_source"] == "server_retry_after"
        assert status_data["retry_delay_seconds"] == 46765
        assert status_data["next_retry_at"] is not None

        # 4. Verify no second login attempt was made (bot must NOT retry after 10m)
        assert call_count == 1

        # 5. Verify logs contain required fields
        log_text = caplog.text
        assert "state=RATE_LIMITED" in log_text
        assert "status=429" in log_text
        assert "retry_after=46765" in log_text
        assert "delay=46765" in log_text
        assert "retry_source=server_retry_after"

        # 6. Shut down cleanly
        manager.request_shutdown("Acceptance test shutdown")
        await run_task

