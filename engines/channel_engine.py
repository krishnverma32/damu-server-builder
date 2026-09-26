"""ChannelEngine — channel operations with global API resilience and rollback support."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

import discord

from core.discord_api.guard import api_guard

log = logging.getLogger("engines.channel_engine")


class ChannelEngine:
    """Manages text and voice channels, ensuring operations respect API rate limits

    and support rollback/cleanup if subsequent transaction steps fail.
    """

    @staticmethod
    def get_channel(guild: discord.Guild, channel_id: int) -> Optional[discord.abc.GuildChannel]:
        """Fetch channel from guild cache."""
        if not channel_id:
            return None
        return guild.get_channel(channel_id)

    @staticmethod
    async def create_text_channel(
        guild: discord.Guild,
        name: str,
        category: Optional[discord.CategoryChannel] = None,
        overwrites: Optional[Mapping[discord.Role | discord.Member, discord.PermissionOverwrite]] = None,
        topic: Optional[str] = None,
        reason: str = "",
    ) -> Optional[discord.TextChannel]:
        """Create a text channel with API guard coordination.

        Returns None if Discord API is globally blocked or creation fails.
        """
        allowed, api_state, retry_at = api_guard.can_execute()
        if not allowed:
            log.warning(
                "[CHANNEL_ENGINE] create_text_channel '%s' blocked by API guard (state=%s, retry_at=%s)",
                name,
                api_state.value,
                retry_at,
            )
            return None

        create_kwargs = {
            "name": name,
            "category": category,
            "overwrites": overwrites or {},
            "reason": reason,
        }
        if topic is not None:
            create_kwargs["topic"] = topic

        try:
            channel = await guild.create_text_channel(**create_kwargs)
            api_guard.record_success()
            return channel
        except discord.HTTPException as exc:
            if exc.status == 429:
                api_guard.record_failure(status=429, body=getattr(exc, "text", ""), error=exc)
            log.error("[CHANNEL_ENGINE] Failed to create channel '%s': %s", name, exc)
            return None
        except Exception as exc:
            log.exception("[CHANNEL_ENGINE] Unexpected error creating channel '%s': %s", name, exc)
            return None

    @staticmethod
    async def delete_channel_safe(
        channel: discord.abc.GuildChannel,
        reason: str = "",
    ) -> bool:
        """Safely delete a channel (e.g. during transaction rollback or auto-delete).

        Handles 404/NotFound without raising, and checks API guard.
        """
        allowed, api_state, _ = api_guard.can_execute()
        if not allowed:
            log.warning(
                "[CHANNEL_ENGINE] delete_channel '%s' deferred/blocked by API guard (state=%s)",
                channel.name,
                api_state.value,
            )
            return False

        try:
            await channel.delete(reason=reason)
            api_guard.record_success()
            log.info("[CHANNEL_ENGINE] Deleted channel %s (reason=%s)", channel.name, reason)
            return True
        except discord.NotFound:
            log.info("[CHANNEL_ENGINE] Channel %s was already deleted.", channel.name)
            return True
        except discord.Forbidden:
            log.error("[CHANNEL_ENGINE] Missing permissions to delete channel %s.", channel.name)
            return False
        except discord.HTTPException as exc:
            if exc.status == 429:
                api_guard.record_failure(status=429, body=getattr(exc, "text", ""), error=exc)
            log.error("[CHANNEL_ENGINE] HTTP error deleting channel %s: %s", channel.name, exc)
            return False
        except Exception as exc:
            log.exception("[CHANNEL_ENGINE] Unexpected error deleting channel %s: %s", channel.name, exc)
            return False
