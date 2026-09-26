"""CategoryEngine — category channel operations with global API resilience."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

import discord

from core.discord_api.guard import api_guard

log = logging.getLogger("engines.category_engine")


class CategoryEngine:
    """Manages category channels with cached lookups and API guard checks."""

    @staticmethod
    def get_category(guild: discord.Guild, category_id: int) -> Optional[discord.CategoryChannel]:
        """Lookup category channel from guild cache."""
        if not category_id:
            return None
        ch = guild.get_channel(category_id)
        if isinstance(ch, discord.CategoryChannel):
            return ch
        return None

    @staticmethod
    async def create_category(
        guild: discord.Guild,
        name: str,
        overwrites: Optional[Mapping[discord.Role | discord.Member, discord.PermissionOverwrite]] = None,
        reason: str = "",
    ) -> Optional[discord.CategoryChannel]:
        """Create a category channel if Discord API is available."""
        allowed, api_state, _ = api_guard.can_execute()
        if not allowed:
            log.warning("CategoryEngine.create_category blocked by API state: %s", api_state.value)
            return None

        try:
            category = await guild.create_category(
                name=name,
                overwrites=overwrites or {},
                reason=reason,
            )
            api_guard.record_success()
            return category
        except discord.HTTPException as exc:
            if exc.status == 429:
                api_guard.record_failure(status=429, body=getattr(exc, "text", ""), error=exc)
            log.error("Failed to create category '%s': %s", name, exc)
            return None
