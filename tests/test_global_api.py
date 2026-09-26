"""Tests for Global Discord API Resilience Layer (Tests 15-20)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from core.discord_api.guard import DiscordAPIGuard, api_guard
from core.discord_api.rate_limit import is_cloudflare_1015, parse_retry_after
from core.discord_api.state import APIState
from core.startup.backoff import calculate_backoff


@pytest.fixture(autouse=True)
def reset_guard():
    api_guard.reset()
    yield
    api_guard.reset()


# ── Test 15: Global Cloudflare 1015 Detection ─────────────────────────────────
def test_cloudflare_1015_detection():
    # 1. By status 429 and error code 1015 in body
    assert is_cloudflare_1015(
        status=429,
        body="<html><body><h1>Error 1015</h1><p>You are being rate limited</p></body></html>",
    )

    # 2. By Cloudflare headers + 429
    assert is_cloudflare_1015(
        status=429,
        body="Rate limited",
        headers={"cf-ray": "8e3b1234abcd", "server": "cloudflare"},
    )

    # 3. Standard Discord 429 is NOT Cloudflare 1015
    assert not is_cloudflare_1015(
        status=429,
        body='{"message": "You are being rate limited.", "retry_after": 2.5, "global": false}',
        headers={"server": "cloudflare-custom-gateway-none"},
    )

    # 4. Status 200 is never Cloudflare 1015
    assert not is_cloudflare_1015(status=200, body="OK")


# ── Test 16: Global API state changes to CLOUDFLARE_BLOCKED ───────────────────
def test_global_state_transitions_to_cloudflare_blocked():
    cf_body = "<html><body>Error 1015: You are being rate limited</body></html>"

    api_guard.record_failure(status=429, body=cf_body)

    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED
    assert api_guard.provider == "cloudflare"
    assert api_guard.is_cloudflare is True
    assert api_guard.retry_at is not None
    assert api_guard.retry_delay > 0.0


# ── Test 17: Requests are prevented while globally blocked ────────────────────
def test_requests_prevented_while_globally_blocked():
    api_guard.record_failure(
        status=429,
        body="Error 1015: You are being rate limited",
        headers={"retry-after": "120"},
    )

    # Attempt execution while blocked
    allowed, state, retry_at = api_guard.can_execute()

    assert allowed is False
    assert state == APIState.CLOUDFLARE_BLOCKED
    assert retry_at is not None
    assert retry_at > datetime.now(timezone.utc)


# ── Test 18: Recovery changes state to AVAILABLE ──────────────────────────────
def test_recovery_transitions_to_available():
    # Force blocked state
    api_guard.record_failure(status=429, body="Rate limited")
    assert api_guard.state == APIState.RATE_LIMITED

    # Expire the deadline artificially
    api_guard._retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # First check transitions to RECOVERING to allow controlled probe
    allowed, state, _ = api_guard.can_execute()
    assert allowed is True
    assert state == APIState.RECOVERING

    # Successful probe transitions back to AVAILABLE
    api_guard.record_success()
    assert api_guard.state == APIState.AVAILABLE
    assert api_guard.retry_at is None
    assert api_guard.consecutive_failures == 0


# ── Test 19: Zero Retry-After cannot produce tight loop ────────────────────────
def test_zero_retry_after_loop_prevention():
    # If Discord or Cloudflare sends Retry-After: 0, guard must not set 0 delay
    delay = api_guard.record_failure(
        status=429,
        body="Error 1015",
        headers={"retry-after": "0"},
    )

    assert delay > 0.0
    assert api_guard.retry_delay > 0.0
    # Must wait before retry, preventing tight loop
    assert api_guard.retry_at > datetime.now(timezone.utc)


# ── Test 20: Server Retry-After is distinct from local backoff ────────────────
def test_server_retry_after_distinct_from_backoff():
    # High server Retry-After (e.g. 10 hours = 36000s)
    server_delay, source = calculate_backoff(attempt=1, retry_after=36000.0)
    assert server_delay == 36000.0
    assert source == "server_retry_after"

    # Local exponential backoff without server header
    local_delay, source_local = calculate_backoff(attempt=1, retry_after=None)
    assert local_delay < 10.0  # ~5s + jitter
    assert source_local == "exponential_backoff"

    # They remain completely separate concepts
    assert server_delay != local_delay
