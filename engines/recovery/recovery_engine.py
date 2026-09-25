"""Recovery Engine — Central recovery coordinator for retries, rollbacks, and safe fallback states."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Sequence, TypeVar

import discord

from core.errors import ErrorCategory, classify_error
from engines.builder.rollback import BuilderRollback
from engines.recovery.retry import with_retry

log = logging.getLogger("engines.recovery.recovery_engine")

T = TypeVar("T")


class RecoveryEngine:
    """Coordinates error recovery strategies across Discord operations."""

    def __init__(self) -> None:
        self.rollback_engine = BuilderRollback()

    async def execute_safe(self, operation: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute operation with automatic retry on transient rate-limits and network hiccups."""
        return await with_retry(operation, *args, **kwargs)

    async def rollback_resources(
        self,
        channels: Sequence[discord.abc.GuildChannel],
        roles: Sequence[discord.Role],
        build_id: str,
    ) -> str:
        """Perform transactional rollback."""
        return await self.rollback_engine.rollback(channels, roles, build_id)

    def recommend_action(self, exc: BaseException) -> str:
        """Recommend immediate user or bot action based on exception classification."""
        category = classify_error(exc)
        if category == ErrorCategory.PERMISSION:
            return "Check bot role permissions in Server Settings -> Roles."
        elif category == ErrorCategory.HIERARCHY:
            return "Move DAMU's role above the target role in Server Settings -> Roles."
        elif category == ErrorCategory.RATE_LIMIT:
            return "Discord is rate limiting. Wait a moment and retry."
        elif category == ErrorCategory.DATABASE:
            return "MongoDB connection failed. Check MONGO_URI in hosting settings."
        elif category == ErrorCategory.NOT_FOUND:
            return "Target resource was not found or was deleted."
        return "Contact server management or check logs."


recovery_engine = RecoveryEngine()
