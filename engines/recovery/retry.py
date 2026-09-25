"""Retry policy implementation — safe retries with exponential backoff and rate limit handling."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, TypeVar

import discord

from engines.recovery.error_classifier import is_retryable

log = logging.getLogger("engines.recovery.retry")

T = TypeVar("T")
MAX_RETRIES = 3


async def with_retry(
    operation: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_delay: float = 1.0,
    max_delay: float = 12.0,
    **kwargs: Any,
) -> T:
    """Execute an async operation with exponential backoff on retryable failures."""
    last_exc: BaseException | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return await operation(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not is_retryable(exc) or attempt == max_retries:
                log.warning("Operation failed on attempt %d/%d (not retrying): %s", attempt, max_retries, exc)
                raise

            # Determine delay: respect Discord RateLimited retry_after if available
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
            if isinstance(exc, discord.RateLimited):
                delay = getattr(exc, "retry_after", delay)
            elif isinstance(exc, discord.HTTPException) and exc.status == 429:
                delay = getattr(exc, "retry_after", delay)

            delay = min(delay, max_delay)
            log.info("Retryable error on attempt %d/%d (%s). Waiting %.1fs...", attempt, max_retries, exc, delay)
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc
