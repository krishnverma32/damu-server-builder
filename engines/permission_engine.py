"""PermissionEngine — unified permission calculation and overwrite management."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

import discord

log = logging.getLogger("engines.permission_engine")

_PERM_MAP: dict[str, int] = {
    "administrator": discord.Permissions.administrator.flag,
    "manage_guild": discord.Permissions.manage_guild.flag,
    "manage_channels": discord.Permissions.manage_channels.flag,
    "manage_roles": discord.Permissions.manage_roles.flag,
    "manage_messages": discord.Permissions.manage_messages.flag,
    "manage_threads": discord.Permissions.manage_threads.flag,
    "kick_members": discord.Permissions.kick_members.flag,
    "ban_members": discord.Permissions.ban_members.flag,
    "send_messages": discord.Permissions.send_messages.flag,
    "view_channel": discord.Permissions.view_channel.flag,
    "read_messages": discord.Permissions.read_messages.flag,
    "read_message_history": discord.Permissions.read_message_history.flag,
    "create_public_threads": discord.Permissions.create_public_threads.flag,
    "create_private_threads": discord.Permissions.create_private_threads.flag,
    "send_messages_in_threads": discord.Permissions.send_messages_in_threads.flag,
    "add_reactions": discord.Permissions.add_reactions.flag,
    "use_external_emojis": discord.Permissions.use_external_emojis.flag,
    "use_external_stickers": discord.Permissions.use_external_stickers.flag,
    "use_application_commands": discord.Permissions.use_application_commands.flag,
    "connect": discord.Permissions.connect.flag,
    "speak": discord.Permissions.speak.flag,
    "mute_members": discord.Permissions.mute_members.flag,
    "deafen_members": discord.Permissions.deafen_members.flag,
    "move_members": discord.Permissions.move_members.flag,
    "manage_nicknames": discord.Permissions.manage_nicknames.flag,
    "mention_everyone": discord.Permissions.mention_everyone.flag,
    "embed_links": discord.Permissions.embed_links.flag,
    "attach_files": discord.Permissions.attach_files.flag,
    "manage_webhooks": discord.Permissions.manage_webhooks.flag,
    "view_audit_log": discord.Permissions.view_audit_log.flag,
}


class PermissionEngine:
    """Manages role and channel permissions across DAMU subsystems."""

    @staticmethod
    def resolve_permissions(perm_names: Sequence[str]) -> discord.Permissions:
        """Convert a list of permission name strings to a discord.Permissions object."""
        value = 0
        for name in perm_names:
            flag = _PERM_MAP.get(name.lower())
            if flag:
                value |= flag
            else:
                log.warning("Unknown permission name: %s", name)
        return discord.Permissions(value)

    @staticmethod
    def build_ticket_overwrites(
        guild: discord.Guild,
        opener: discord.Member | discord.User,
        support_role: Optional[discord.Role] = None,
        mod_role: Optional[discord.Role] = None,
    ) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
        """Construct standard permission overwrites for a private ticket channel."""
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            opener: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }

        # Bot self-permissions
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            )

        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )

        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )

        return overwrites

    @staticmethod
    def validate_bot_permissions(
        guild: discord.Guild,
        required_perms: Sequence[str] = (
            "manage_channels",
            "send_messages",
            "manage_messages",
            "attach_files",
            "embed_links",
        ),
    ) -> tuple[bool, list[str]]:
        """Verify bot has necessary guild permissions.

        Returns (all_present: bool, missing_permissions: list[str])
        """
        if not guild.me:
            return False, list(required_perms)
        guild_perms = guild.me.guild_permissions
        missing = [
            perm for perm in required_perms if not getattr(guild_perms, perm, False)
        ]
        return len(missing) == 0, missing
