"""Ticket service backed by async SQLite."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import discord

from services.database import get_database

log = logging.getLogger("services.ticket")


def _key(guild_id: int, user_id: int) -> str:
    return f"{guild_id}_{user_id}"


async def _get_ticket_row(guild_id: int, user_id: int) -> Any | None:
    db = get_database()
    conn = await db.connect()
    async with conn.execute(
        """
        SELECT data, open
        FROM tickets
        WHERE guild_id = ? AND user_id = ?
        """,
        (str(guild_id), str(user_id)),
    ) as cursor:
        return await cursor.fetchone()


async def has_open_ticket(guild_id: int, user_id: int) -> bool:
    row = await _get_ticket_row(guild_id, user_id)
    return bool(row and row["open"])


async def open_ticket(guild_id: int, user_id: int, channel_id: int) -> None:
    db = get_database()
    conn = await db.connect()
    data = {
        "channel_id": channel_id,
        "user_id": user_id,
        "guild_id": guild_id,
        "open": True,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "messages": [],
    }
    await conn.execute(
        """
        INSERT INTO tickets (guild_id, user_id, data, open, channel_id, updated_at)
        VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            data = excluded.data,
            open = excluded.open,
            channel_id = excluded.channel_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (str(guild_id), str(user_id), json.dumps(data), str(channel_id)),
    )
    await conn.commit()


async def close_ticket(guild_id: int, user_id: int, reason: str) -> dict[str, Any] | None:
    row = await _get_ticket_row(guild_id, user_id)
    if row is None:
        return None

    data = json.loads(row["data"])
    data["open"] = False
    data["closed_at"] = datetime.now(timezone.utc).isoformat()
    data["close_reason"] = reason

    db = get_database()
    conn = await db.connect()
    await conn.execute(
        """
        UPDATE tickets
        SET data = ?, open = 0, updated_at = CURRENT_TIMESTAMP
        WHERE guild_id = ? AND user_id = ?
        """,
        (json.dumps(data), str(guild_id), str(user_id)),
    )
    await conn.commit()
    return data


async def get_ticket(guild_id: int, user_id: int) -> dict[str, Any] | None:
    row = await _get_ticket_row(guild_id, user_id)
    if row is None:
        return None
    return json.loads(row["data"])


async def generate_transcript(channel: discord.TextChannel, limit: int = 500) -> str:
    """Read up to *limit* messages from *channel* and format as a plaintext transcript."""
    lines: list[str] = []
    async for msg in channel.history(limit=limit, oldest_first=True):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"[{ts}] {msg.author}: {msg.content}")
    return "\n".join(lines)
