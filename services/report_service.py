"""Server and owner report aggregation built on daily_stats and ai_usage."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import discord

import config
from services.database import get_database
from services.embed_service import info_embed

log = logging.getLogger("services.report_service")

REPORT_DAYS = 7
GLOBAL_AI_LIMIT_WARNING_RATIO = 0.8


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_key(day: date | None = None) -> str:
    return (day or _utc_now().date()).isoformat()


def _period_dates(days: int = REPORT_DAYS) -> list[str]:
    today = _utc_now().date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days)]


def _empty_stats() -> dict[str, Any]:
    return {
        "members": {"joins": 0, "leaves": 0},
        "moderation": {"kicks": 0, "bans": 0, "warns": 0, "mutes": 0},
        "tickets": {"opened": 0, "closed": 0},
        "automod": {"offenses": 0},
        "ai": {"messages": 0},
    }


def _merge_stats(total: dict[str, Any], data: dict[str, Any]) -> None:
    for section, values in _empty_stats().items():
        section_total = total.setdefault(section, {})
        section_data = data.get(section, {}) if isinstance(data, dict) else {}
        for key in values:
            section_total[key] = int(section_total.get(key, 0)) + int(section_data.get(key, 0))


async def record_counter(guild_id: int, section: str, name: str, amount: int = 1) -> None:
    """Increment one daily report counter for one guild."""
    if amount <= 0:
        return
    db = get_database()
    conn = await db.connect()
    key = _date_key()
    async with conn.execute(
        "SELECT data FROM daily_stats WHERE guild_id = ? AND date = ?",
        (str(guild_id), key),
    ) as cursor:
        row = await cursor.fetchone()

    stats: dict[str, Any] = {}
    if row is not None:
        try:
            existing = json.loads(row["data"])
            if isinstance(existing, dict):
                stats = existing
        except json.JSONDecodeError:
            log.warning("Invalid daily_stats JSON for guild %s on %s", guild_id, key)

    defaults = _empty_stats()
    for default_section, default_values in defaults.items():
        current = stats.get(default_section)
        if not isinstance(current, dict):
            stats[default_section] = default_values
            continue
        for default_name, default_amount in default_values.items():
            current.setdefault(default_name, default_amount)

    stats.setdefault(section, {})
    stats[section][name] = int(stats[section].get(name, 0)) + amount
    await conn.execute(
        """
        INSERT INTO daily_stats (guild_id, date, data, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(guild_id, date) DO UPDATE SET
            data = excluded.data,
            updated_at = CURRENT_TIMESTAMP
        """,
        (str(guild_id), key, json.dumps(stats)),
    )
    await conn.commit()


async def _stats_for_guild(guild_id: int, days: int = REPORT_DAYS) -> dict[str, Any]:
    db = get_database()
    conn = await db.connect()
    total = _empty_stats()
    dates = _period_dates(days)
    placeholders = ",".join("?" for _ in dates)
    async with conn.execute(
        f"""
        SELECT data FROM daily_stats
        WHERE guild_id = ? AND date IN ({placeholders})
        """,
        (str(guild_id), *dates),
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            _merge_stats(total, data)
    return total


async def _open_ticket_count(guild_id: int) -> int:
    db = get_database()
    conn = await db.connect()
    async with conn.execute(
        "SELECT COUNT(*) AS total FROM tickets WHERE guild_id = ? AND open = 1",
        (str(guild_id),),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row["total"] or 0)


async def _ai_tokens_for_guild(guild_id: int, days: int = REPORT_DAYS) -> int:
    db = get_database()
    conn = await db.connect()
    dates = _period_dates(days)
    placeholders = ",".join("?" for _ in dates)
    async with conn.execute(
        f"""
        SELECT COALESCE(SUM(tokens_used), 0) AS total
        FROM ai_usage
        WHERE guild_id = ? AND date IN ({placeholders})
        """,
        (str(guild_id), *dates),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row["total"] or 0)


def _format_failed_cogs(failed_cogs: dict[str, str]) -> str:
    if not failed_cogs:
        return "None"
    lines = [f"`{name}`" for name in sorted(failed_cogs)]
    return "\n".join(lines)[:1000]


async def build_server_report_embed(
    bot: discord.Client,
    guild: discord.Guild,
    days: int = REPORT_DAYS,
) -> discord.Embed:
    """Build a report for exactly one guild."""
    stats = await _stats_for_guild(guild.id, days)
    joins = int(stats["members"]["joins"])
    leaves = int(stats["members"]["leaves"])
    moderation = stats["moderation"]
    tickets = stats["tickets"]
    automod = stats["automod"]
    ai = stats["ai"]
    uptime = _utc_now() - getattr(bot, "start_time", _utc_now())
    failed_cogs = getattr(bot, "failed_cogs", {})
    open_tickets = await _open_ticket_count(guild.id)
    ai_tokens = await _ai_tokens_for_guild(guild.id, days)

    embed = info_embed(
        f"{guild.name} Server Report",
        f"Period: **last {days} days**\nCurrent members: **{guild.member_count or 0:,}**",
    )
    embed.add_field(name="Member Change", value=f"Joins: **{joins}**\nLeaves: **{leaves}**\nNet: **{joins - leaves:+}**")
    embed.add_field(
        name="Moderation",
        value=(
            f"Kicks: **{int(moderation['kicks'])}**\n"
            f"Bans: **{int(moderation['bans'])}**\n"
            f"Warns: **{int(moderation['warns'])}**\n"
            f"Mutes: **{int(moderation['mutes'])}**"
        ),
    )
    embed.add_field(
        name="Tickets",
        value=f"Opened: **{int(tickets['opened'])}**\nClosed: **{int(tickets['closed'])}**\nCurrently open: **{open_tickets}**",
    )
    embed.add_field(name="AutoMod", value=f"Offenses: **{int(automod['offenses'])}**")
    embed.add_field(name="AI Usage", value=f"Messages: **{int(ai['messages'])}**\nTokens: **{ai_tokens:,}**")
    embed.add_field(name="Bot Health", value=f"Uptime: **{str(uptime).split('.')[0]}**\nFailed cogs: **{len(failed_cogs)}**")
    if failed_cogs:
        embed.add_field(name="Cog Load Failures", value=_format_failed_cogs(failed_cogs), inline=False)
    return embed


async def build_global_report_embed(
    bot: discord.Client,
    days: int = REPORT_DAYS,
) -> discord.Embed:
    """Build the bot-owner-only global report across all current guilds."""
    db = get_database()
    conn = await db.connect()
    async with conn.execute(
        "SELECT COALESCE(SUM(tokens_used), 0) AS total FROM ai_usage WHERE guild_id != '0'"
    ) as cursor:
        row = await cursor.fetchone()
    total_tokens = int(row["total"] or 0)

    today = _date_key()
    async with conn.execute(
        """
        SELECT guild_id, COALESCE(SUM(tokens_used), 0) AS total
        FROM ai_usage
        WHERE date = ?
        GROUP BY guild_id
        """,
        (today,),
    ) as cursor:
        usage_rows = await cursor.fetchall()

    warning_threshold = int(config.AI_DAILY_TOKEN_LIMIT * GLOBAL_AI_LIMIT_WARNING_RATIO)
    current_guild_ids = {str(guild.id) for guild in bot.guilds}
    near_limit = [
        (str(row["guild_id"]), int(row["total"] or 0))
        for row in usage_rows
        if str(row["guild_id"]) in current_guild_ids and int(row["total"] or 0) >= warning_threshold
    ]
    guild_lines = [
        f"{guild.name} (`{guild.id}`): **{guild.member_count or 0:,}** members"
        for guild in bot.guilds
    ]
    limit_lines = [
        f"`{guild_id}`: **{tokens:,}/{config.AI_DAILY_TOKEN_LIMIT:,}** today"
        for guild_id, tokens in near_limit
    ]
    failed_cogs = getattr(bot, "failed_cogs", {})

    embed = info_embed(
        "Global Bot Owner Report",
        f"Guilds: **{len(bot.guilds)}**\nTotal AI tokens recorded: **{total_tokens:,}**",
    )
    embed.add_field(
        name="Guilds",
        value=("\n".join(guild_lines) or "No guilds")[:1000],
        inline=False,
    )
    embed.add_field(
        name="Cog / Error Summary",
        value=_format_failed_cogs(failed_cogs),
        inline=False,
    )
    embed.add_field(
        name="AI Daily Limit Watch",
        value=("\n".join(limit_lines) or "No guilds near the daily token limit.")[:1000],
        inline=False,
    )
    return embed
