"""Level / XP service backed by async SQLite."""

from __future__ import annotations

from services.database import get_database


def xp_for_level(level: int) -> int:
    """XP required to reach *level* from level 0."""
    return int(100 * (level ** 1.5))


def level_from_xp(xp: int) -> int:
    """Compute level from total XP."""
    level = 0
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


async def add_xp(guild_id: int, user_id: int, amount: int) -> tuple[int, int, bool]:
    """Add *amount* XP. Returns ``(new_xp, new_level, leveled_up)``."""
    db = get_database()
    conn = await db.connect()
    async with conn.execute(
        "SELECT xp, level FROM levels WHERE guild_id = ? AND user_id = ?",
        (str(guild_id), str(user_id)),
    ) as cursor:
        row = await cursor.fetchone()
    old_xp = int(row["xp"]) if row else 0
    old_level = int(row["level"]) if row else 0
    new_xp = old_xp + amount
    new_level = level_from_xp(new_xp)
    leveled_up = new_level > old_level
    await conn.execute(
        """
        INSERT INTO levels (guild_id, user_id, xp, level, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            xp = excluded.xp,
            level = excluded.level,
            updated_at = CURRENT_TIMESTAMP
        """,
        (str(guild_id), str(user_id), new_xp, new_level),
    )
    await conn.commit()
    return new_xp, new_level, leveled_up


async def get_stats(guild_id: int, user_id: int) -> dict[str, int]:
    db = get_database()
    conn = await db.connect()
    async with conn.execute(
        "SELECT xp, level FROM levels WHERE guild_id = ? AND user_id = ?",
        (str(guild_id), str(user_id)),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return {"xp": 0, "level": 0}
    return {"xp": int(row["xp"]), "level": int(row["level"])}


async def set_xp(guild_id: int, user_id: int, xp: int) -> int:
    db = get_database()
    conn = await db.connect()
    level = level_from_xp(xp)
    await conn.execute(
        """
        INSERT INTO levels (guild_id, user_id, xp, level, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            xp = excluded.xp,
            level = excluded.level,
            updated_at = CURRENT_TIMESTAMP
        """,
        (str(guild_id), str(user_id), xp, level),
    )
    await conn.commit()
    return level


async def get_leaderboard(guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
    """Return ``[(user_id, xp, level), ...]`` sorted by XP descending."""
    db = get_database()
    conn = await db.connect()
    async with conn.execute(
        """
        SELECT user_id, xp, level
        FROM levels
        WHERE guild_id = ?
        ORDER BY xp DESC
        LIMIT ?
        """,
        (str(guild_id), limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [(int(row["user_id"]), int(row["xp"]), int(row["level"])) for row in rows]
