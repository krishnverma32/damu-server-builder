"""Channel and category cloning utilities with full permission and property duplication."""
from __future__ import annotations

import logging
from typing import Any

import discord

log = logging.getLogger(__name__)


async def clone_channel_resource(
    channel: discord.abc.GuildChannel,
    new_name: str,
    target_category: discord.CategoryChannel | None = None,
    sync_permissions: bool = False,
) -> discord.abc.GuildChannel:
    """Duplicate a channel with all settings and permission overwrites."""
    guild = channel.guild
    category = target_category if target_category is not None else channel.category
    overwrites = None if sync_permissions else channel.overwrites

    if isinstance(channel, discord.TextChannel):
        is_news = channel.is_news() and "COMMUNITY" in guild.features
        return await guild.create_text_channel(
            name=new_name,
            category=category,
            topic=channel.topic,
            slowmode_delay=channel.slowmode_delay,
            nsfw=channel.nsfw,
            news=is_news,
            overwrites=overwrites,
            reason=f"Damu: cloned from #{channel.name}",
        )
    elif isinstance(channel, discord.VoiceChannel):
        bitrate = min(channel.bitrate, guild.bitrate_limit)
        return await guild.create_voice_channel(
            name=new_name,
            category=category,
            bitrate=bitrate,
            user_limit=channel.user_limit,
            overwrites=overwrites,
            reason=f"Damu: cloned from {channel.name}",
        )
    elif isinstance(channel, discord.StageChannel):
        bitrate = min(channel.bitrate, guild.bitrate_limit)
        return await guild.create_stage_channel(
            name=new_name,
            category=category,
            topic=channel.topic,
            bitrate=bitrate,
            user_limit=channel.user_limit,
            overwrites=overwrites,
            reason=f"Damu: cloned from {channel.name}",
        )
    elif isinstance(channel, discord.ForumChannel):
        return await guild.create_forum(
            name=new_name,
            category=category,
            topic=channel.topic,
            slowmode_delay=channel.slowmode_delay,
            nsfw=channel.nsfw,
            default_thread_slowmode_delay=channel.default_thread_slowmode_delay,
            default_auto_archive_duration=channel.default_auto_archive_duration,
            default_sort_order=channel.default_sort_order,
            default_layout=channel.default_layout,
            overwrites=overwrites,
            available_tags=channel.available_tags,
            reason=f"Damu: cloned from {channel.name}",
        )
    else:
        # Generic fallback
        return await channel.clone(name=new_name, reason=f"Damu: cloned from {channel.name}")


async def clone_category_resource(
    category: discord.CategoryChannel,
    new_name: str,
) -> tuple[discord.CategoryChannel, list[discord.abc.GuildChannel]]:
    """Duplicate an entire category and all of its channels and permissions."""
    guild = category.guild
    new_cat = await guild.create_category(
        name=new_name,
        overwrites=category.overwrites,
        position=category.position + 1,
        reason=f"Damu: cloned from category {category.name}",
    )

    cloned_channels: list[discord.abc.GuildChannel] = []
    for ch in category.channels:
        cloned_ch = await clone_channel_resource(
            channel=ch,
            new_name=ch.name,
            target_category=new_cat,
            sync_permissions=ch.permissions_synced,
        )
        cloned_channels.append(cloned_ch)

    return new_cat, cloned_channels
