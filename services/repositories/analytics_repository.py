"""SQLite-backed Analytics Repository for daily server events."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.analytics")


class AnalyticsRepository(BaseRepository):
    """Tracks message, member, and command counts in daily_stats."""

    @staticmethod
    def today_str() -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    async def increment(self, guild_id: int, section: str, key: str, amount: int = 1) -> None:
        today = self.today_str()
        conn = await self.connect()
        async with conn.execute(
            "SELECT data FROM daily_stats WHERE guild_id = ? AND date = ?",
            (str(guild_id), today),
        ) as cursor:
            row = await cursor.fetchone()

        data: dict[str, Any] = self.loads(row["data"], {}) if row else {}
        if section not in data or not isinstance(data[section], dict):
            data[section] = {}

        data[section][key] = int(data[section].get(key, 0)) + amount

        await conn.execute(
            """
            INSERT INTO daily_stats (guild_id, date, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, date) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(guild_id), today, self.dumps(data)),
        )
        await conn.commit()

    async def get_stats_for_days(self, guild_id: int, days: int = 7) -> list[tuple[str, dict[str, Any]]]:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        date_keys = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days)]
        conn = await self.connect()

        results = []
        for d in date_keys:
            async with conn.execute(
                "SELECT data FROM daily_stats WHERE guild_id = ? AND date = ?",
                (str(guild_id), d),
            ) as cursor:
                row = await cursor.fetchone()
            data = self.loads(row["data"], {}) if row else {}
            results.append((d, data))
        return results
