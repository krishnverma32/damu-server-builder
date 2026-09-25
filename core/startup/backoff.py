"""Exponential backoff calculation with jitter and sanitized Retry-After precedence."""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass

log = logging.getLogger("core.startup.backoff")

# Defaults for environment configurations
DEFAULT_BASE_BACKOFF: float = 5.0
DEFAULT_MAX_BACKOFF: float = 600.0  # 10 minutes
DEFAULT_JITTER_RATIO: float = 0.25
DEFAULT_MAX_ATTEMPTS: int = 0  # 0 = unlimited retries for transient failures
DEFAULT_MAX_RETRY_WINDOW: float = 0.0  # 0 = unlimited window


def _get_float_env(var_name: str, default: float, min_val: float, max_val: float) -> float:
    raw = os.getenv(var_name)
    if not raw:
        return default
    try:
        val = float(raw.strip().strip('"').strip("'"))
        return max(min_val, min(max_val, val))
    except (ValueError, TypeError):
        return default


def _get_int_env(var_name: str, default: int, min_val: int, max_val: int) -> int:
    raw = os.getenv(var_name)
    if not raw:
        return default
    try:
        val = int(raw.strip().strip('"').strip("'"))
        return max(min_val, min(max_val, val))
    except (ValueError, TypeError):
        return default


@dataclass
class StartupBackoff:
    """Calculates retry delays with exponential growth, jitter, and Retry-After precedence."""

    base_delay: float = DEFAULT_BASE_BACKOFF
    max_delay: float = DEFAULT_MAX_BACKOFF
    jitter_ratio: float = DEFAULT_JITTER_RATIO
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_retry_window: float = DEFAULT_MAX_RETRY_WINDOW

    @classmethod
    def from_env(cls) -> StartupBackoff:
        """Create backoff configuration parsed and clamped from environment variables."""
        base = _get_float_env("STARTUP_BASE_BACKOFF", DEFAULT_BASE_BACKOFF, 1.0, 60.0)
        max_d = _get_float_env("STARTUP_MAX_BACKOFF", DEFAULT_MAX_BACKOFF, 10.0, 3600.0)
        if base > max_d:
            base = max_d
        jitter = _get_float_env("STARTUP_JITTER", DEFAULT_JITTER_RATIO, 0.0, 1.0)
        max_att = _get_int_env("STARTUP_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 0, 1000)
        max_win = _get_float_env("STARTUP_MAX_RETRY_WINDOW", DEFAULT_MAX_RETRY_WINDOW, 0.0, 86400.0)

        return cls(
            base_delay=base,
            max_delay=max_d,
            jitter_ratio=jitter,
            max_attempts=max_att,
            max_retry_window=max_win,
        )

    def calculate_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Calculate the next retry sleep duration.

        Precedence Rule:
        When Discord/Cloudflare supplies Retry-After, that value MUST take precedence
        over normal exponential backoff.
        """
        attempt = max(1, attempt)

        # ── 1. Retry-After Precedence ──────────────────────────────────────────
        if retry_after is not None:
            try:
                sanitized_ra = float(retry_after)
                if sanitized_ra > 0:
                    # Sanitize: clamp between 1.0s and max_delay
                    clamped_ra = min(self.max_delay, max(1.0, sanitized_ra))
                    # Add small positive jitter (0.1s to 0.5s) to avoid synchronised thundering herd
                    jitter = random.uniform(0.1, 0.5)
                    final_delay = min(self.max_delay, clamped_ra + jitter)
                    log.info(
                        "[STARTUP] Retry-After header honored: raw=%.2fs, sanitized=%.2fs, final_delay=%.2fs",
                        sanitized_ra,
                        clamped_ra,
                        final_delay,
                    )
                    return final_delay
            except (ValueError, TypeError):
                log.warning("[STARTUP] Invalid Retry-After value received (%s). Falling back to backoff.", retry_after)

        # ── 2. Exponential Backoff with Jitter ────────────────────────────────
        # attempt 1: base_delay * 2^0 = base_delay
        # attempt 2: base_delay * 2^1 = 2 * base_delay
        exponent = min(10, attempt - 1)
        raw_backoff = self.base_delay * (2 ** exponent)
        clamped_backoff = min(self.max_delay, raw_backoff)

        # Apply bounded random jitter (e.g. +/- jitter_ratio)
        floor = min(1.0, self.base_delay)
        if self.jitter_ratio > 0:
            jitter_delta = clamped_backoff * self.jitter_ratio * random.uniform(-1.0, 1.0)
            final_delay = max(floor, min(self.max_delay, clamped_backoff + jitter_delta))
        else:
            final_delay = max(floor, clamped_backoff)

        return round(final_delay, 2)

    def is_attempt_allowed(self, attempt: int) -> bool:
        """Check if additional retry attempts are permitted under max_attempts."""
        if self.max_attempts <= 0:
            return True
        return attempt <= self.max_attempts

    def reset(self) -> None:
        """Reset state. Called ONLY after a genuine successful Discord connection."""
        log.debug("[STARTUP] Backoff state reset following successful connection.")
