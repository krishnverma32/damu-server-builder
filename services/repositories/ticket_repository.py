"""SQLite-backed Ticket Repository with legacy MongoDB / JSON fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import config
from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.ticket")


class TicketRepository(BaseRepository):
    """Manages ticket configurations, open tickets, claimed tickets, and blacklist in SQLite."""

    SECTION = "ticket_config"

    async def get_guild(self, guild_id: int) -> dict[str, Any]:
        """Fetch the ticket configuration document for *guild_id*."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT data FROM guild_settings WHERE guild_id = ? AND section = ?",
            (str(guild_id), self.SECTION),
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            return self.loads(row["data"], {})

        # Migration fallback: try MongoDB if configured, then local JSON
        migrated = await self._try_legacy_migration(guild_id)
        if migrated:
            await self.save_guild(guild_id, migrated)
            return migrated

        return {}

    async def save_guild(self, guild_id: int, data: dict[str, Any]) -> None:
        """Upsert the ticket configuration document for *guild_id*."""
        conn = await self.connect()
        clean_data = dict(data)
        clean_data.pop("_id", None)
        await conn.execute(
            """
            INSERT INTO guild_settings (guild_id, section, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, section) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(guild_id), self.SECTION, self.dumps(clean_data)),
        )
        await conn.commit()

    get_config = get_guild
    set_config = save_guild

    async def get_key(self, guild_id: int, key: str, default: Any = None) -> Any:
        data = await self.get_guild(guild_id)
        return data.get(key, default)

    async def set_key(self, guild_id: int, key: str, value: Any) -> None:
        data = await self.get_guild(guild_id)
        data[key] = value
        await self.save_guild(guild_id, data)

    async def delete_key(self, guild_id: int, key: str) -> None:
        data = await self.get_guild(guild_id)
        if key in data:
            data.pop(key, None)
            await self.save_guild(guild_id, data)

    async def _try_legacy_migration(self, guild_id: int) -> dict[str, Any] | None:
        """Attempt to read legacy ticket data from MongoDB or local JSON if exists."""
        # 1. MongoDB fallback if MONGO_URI is set
        if config.MONGO_URI:
            try:
                import motor.motor_asyncio
                client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=2000)
                doc = await client["ticket_bot"]["guild_configs"].find_one({"_id": str(guild_id)})
                if doc:
                    doc.pop("_id", None)
                    log.info("Migrated ticket config from MongoDB for guild %s", guild_id)
                    return doc
            except Exception as exc:
                log.debug("MongoDB legacy ticket migration skipped: %s", exc)

        # 2. Local JSON fallback
        legacy_file = f"{config.DATA_DIR}/tickets/ticket_log.json"
        if os.path.exists(legacy_file):
            try:
                with open(legacy_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if str(guild_id) in raw:
                    return raw[str(guild_id)]
            except Exception:
                pass

        return None
