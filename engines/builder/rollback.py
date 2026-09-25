"""Rollback Engine — Safely removes partially created channels, categories, and roles."""

from __future__ import annotations

import logging
from typing import Sequence

import discord

log = logging.getLogger("engines.builder.rollback")


class BuilderRollback:
    """Manages transactional cleanup when a server build encounters an error."""

    async def rollback(
        self,
        created_channels: Sequence[discord.abc.GuildChannel],
        created_roles: Sequence[discord.Role],
        build_id: str,
    ) -> str:
        """Delete created channels and roles in reverse order."""
        ch_deleted = 0
        ro_deleted = 0

        # Delete channels first (children before categories)
        for ch in reversed(created_channels):
            try:
                await ch.delete(reason=f"Rollback for DAMU build {build_id}")
                ch_deleted += 1
            except Exception as exc:
                log.warning("Failed to delete channel %s during rollback: %s", ch.name, exc)

        # Delete roles next
        for role in reversed(created_roles):
            try:
                await role.delete(reason=f"Rollback for DAMU build {build_id}")
                ro_deleted += 1
            except Exception as exc:
                log.warning("Failed to delete role %s during rollback: %s", role.name, exc)

        summary = f"Rolled back {ch_deleted} channels and {ro_deleted} roles."
        log.info("Build %s rollback completed: %s", build_id, summary)
        return summary
