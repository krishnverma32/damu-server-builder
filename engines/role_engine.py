"""RoleEngine — unified role lookup, creation, and hierarchy validation."""

from __future__ import annotations

import logging
from typing import Optional

import discord

from core.discord_api.guard import api_guard

log = logging.getLogger("engines.role_engine")


class RoleEngine:
    """Manages role lookups and operations with global API guard checks."""

    @staticmethod
    def get_role(guild: discord.Guild, role_id: int) -> Optional[discord.Role]:
        """Fetch role from guild cache without unnecessary REST calls."""
        if not role_id:
            return None
        return guild.get_role(role_id)

    @staticmethod
    def can_manage_role(guild: discord.Guild, role: discord.Role) -> bool:
        """Check if bot has permissions and hierarchy position to manage role."""
        if not guild.me or not guild.me.guild_permissions.manage_roles:
            return False
        return guild.me.top_role > role and not role.managed
