"""Guild snapshot extractor and restore converter."""
from __future__ import annotations

import logging
from typing import Any

import discord

from builder.models import ServerConfig

log = logging.getLogger(__name__)


def _perms_to_list(perms: discord.Permissions) -> list[str]:
    """Convert a discord.Permissions instance to a list of enabled flag names."""
    return [flag for flag, val in perms if val]


def _overwrites_to_list(
    channel_or_cat: discord.abc.GuildChannel,
) -> list[dict[str, Any]]:
    """Convert permission overwrites to the Damu schema format."""
    overwrites_list: list[dict[str, Any]] = []
    for target, ow in channel_or_cat.overwrites.items():
        allow_flags = [f for f, v in ow if v is True]
        deny_flags = [f for f, v in ow if v is False]
        if not allow_flags and not deny_flags:
            continue

        item: dict[str, Any] = {"allow": allow_flags, "deny": deny_flags}
        if isinstance(target, discord.Role):
            item["role"] = "@everyone" if target.is_default() else target.name
        elif isinstance(target, discord.Member):
            item["member"] = str(target.id)
        overwrites_list.append(item)
    return overwrites_list


def take_guild_snapshot(guild: discord.Guild) -> dict[str, Any]:
    """Extract full guild layout and configuration into a clean ServerConfig dict.

    Never stores API tokens, webhooks, or member private data.
    """
    roles_list: list[dict[str, Any]] = []
    for role in guild.roles:
        if role.is_default() or role.managed:
            continue
        roles_list.append(
            {
                "name": role.name,
                "color": f"#{role.colour.value:06x}" if role.colour.value else "blurple",
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "permissions": _perms_to_list(role.permissions),
            }
        )

    categories_list: list[dict[str, Any]] = []
    for cat in guild.categories:
        cat_data: dict[str, Any] = {
            "name": cat.name,
            "permission_overwrites": _overwrites_to_list(cat),
            "channels": [],
        }

        for ch in cat.channels:
            ch_data: dict[str, Any] = {
                "name": ch.name,
                "permission_overwrites": _overwrites_to_list(ch),
            }
            if isinstance(ch, discord.TextChannel):
                ch_data["type"] = "announcement" if ch.is_news() else "text"
                ch_data["topic"] = ch.topic or ""
                ch_data["slowmode"] = ch.slowmode_delay
                ch_data["nsfw"] = ch.nsfw
            elif isinstance(ch, discord.VoiceChannel):
                ch_data["type"] = "voice"
                ch_data["bitrate"] = ch.bitrate
                ch_data["user_limit"] = ch.user_limit
            elif isinstance(ch, discord.StageChannel):
                ch_data["type"] = "stage"
                ch_data["topic"] = ch.topic or ""
                ch_data["bitrate"] = ch.bitrate
                ch_data["user_limit"] = ch.user_limit
            elif isinstance(ch, discord.ForumChannel):
                ch_data["type"] = "forum"
                ch_data["topic"] = ch.topic or ""
                ch_data["slowmode"] = ch.slowmode_delay
                ch_data["nsfw"] = ch.nsfw
            else:
                ch_data["type"] = "text"

            cat_data["channels"].append(ch_data)

        categories_list.append(cat_data)

    # Root channels (channels not in any category)
    root_channels = [c for c in guild.channels if c.category is None and not isinstance(c, discord.CategoryChannel)]
    if root_channels:
        root_cat_data: dict[str, Any] = {
            "name": "General",
            "permission_overwrites": [],
            "channels": [],
        }
        for ch in root_channels:
            ch_data = {"name": ch.name, "type": "text", "permission_overwrites": _overwrites_to_list(ch)}
            if isinstance(ch, discord.VoiceChannel):
                ch_data["type"] = "voice"
            root_cat_data["channels"].append(ch_data)
        categories_list.insert(0, root_cat_data)

    snapshot: dict[str, Any] = {
        "server_name": guild.name,
        "roles": roles_list,
        "categories": categories_list,
    }
    return snapshot


def validate_snapshot_data(snapshot_dict: dict[str, Any]) -> ServerConfig:
    """Validate snapshot dictionary through ServerConfig schema."""
    return ServerConfig.from_dict(snapshot_dict)
