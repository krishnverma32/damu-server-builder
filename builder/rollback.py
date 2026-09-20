"""Best-effort compensation for this invocation's newly created resources only."""
from __future__ import annotations

import logging
from collections.abc import Sequence

import discord

log = logging.getLogger(__name__)


async def rollback_created(
    channels: Sequence[discord.abc.GuildChannel], roles: Sequence[discord.Role],
) -> list[int]:
    """Return IDs that could not be removed; never claim complete restoration."""
    failed: list[int] = []
    for resource in [*reversed(channels), *reversed(roles)]:
        try:
            await resource.delete(reason="Server build rollback")
        except discord.NotFound:
            continue
        except discord.HTTPException:
            failed.append(resource.id)
            log.exception("Rollback failed for resource %s", resource.id)
    return failed
