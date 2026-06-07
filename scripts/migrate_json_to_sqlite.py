"""Migrate legacy JSON state into SQLite.

Run from the project root:
    python scripts/migrate_json_to_sqlite.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from services.database import get_database  # noqa: E402
from services.level_service import level_from_xp  # noqa: E402


def _load_json(path: str) -> dict[str, Any]:
    file_path = ROOT / path
    if not file_path.exists():
        print(f"skip: {path} not found")
        return {}

    try:
        raw = file_path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(f"error: {path} is invalid JSON: {exc}")
        return {}


async def migrate_ai_memory() -> int:
    db = get_database()
    records = _load_json(config.MEMORY_FILE)
    count = 0
    for user_id, data in records.items():
        if not isinstance(data, dict):
            continue
        data.setdefault("persona", "default")
        data.setdefault("history", [])
        await db.set("ai_memory", str(user_id), data)
        count += 1
    return count


async def migrate_levels() -> int:
    db = get_database()
    conn = await db.connect()
    records = _load_json(config.XP_FILE)
    count = 0

    for guild_id, guild_data in records.items():
        if not isinstance(guild_data, dict):
            continue
        for user_id, raw_stats in guild_data.items():
            if isinstance(raw_stats, dict):
                xp = int(raw_stats.get("xp", 0))
                level = int(raw_stats.get("level", level_from_xp(xp)))
            else:
                xp = int(raw_stats)
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
            count += 1

    await conn.commit()
    return count


async def migrate_tickets() -> int:
    db = get_database()
    conn = await db.connect()
    records = _load_json(config.TICKET_LOG_FILE)
    count = 0

    for fallback_key, data in records.items():
        if not isinstance(data, dict):
            continue
        guild_id = str(data.get("guild_id") or fallback_key.split("_", 1)[0])
        user_id = str(data.get("user_id") or fallback_key.rsplit("_", 1)[-1])
        channel_id = str(data.get("channel_id", ""))
        is_open = 1 if data.get("open", False) else 0

        await conn.execute(
            """
            INSERT INTO tickets (guild_id, user_id, data, open, channel_id, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                data = excluded.data,
                open = excluded.open,
                channel_id = excluded.channel_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (guild_id, user_id, json.dumps(data), is_open, channel_id),
        )
        count += 1

    await conn.commit()
    return count


async def main() -> None:
    db = get_database()
    await db.create_tables()
    ai_count = await migrate_ai_memory()
    level_count = await migrate_levels()
    ticket_count = await migrate_tickets()
    await db.close()
    print(f"migrated: ai_memory={ai_count}, levels={level_count}, tickets={ticket_count}")


if __name__ == "__main__":
    asyncio.run(main())
