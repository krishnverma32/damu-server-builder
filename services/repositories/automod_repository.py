"""SQLite-backed AutoMod Repository with legacy MongoDB / JSON fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import config
from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.automod")


class AutoModRepository(BaseRepository):
    """Manages AutoMod offenses, ignored channels, and bypass roles in SQLite."""

    SECTION = "automod_state"

    async def get_state(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fetch ``(offenses, settings)`` from SQLite, migrating if empty."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT data FROM guild_settings WHERE guild_id = 'global' AND section = ?",
            (self.SECTION,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            data = self.loads(row["data"], {})
            return data.get("offenses", {}), data.get("settings", {})

        # Attempt legacy migration
        migrated = await self._try_legacy_migration()
        if migrated:
            await self.save_state(migrated.get("offenses", {}), migrated.get("settings", {}))
            return migrated.get("offenses", {}), migrated.get("settings", {})

        return {}, {}

    async def get_config(self, guild_id: int | str = "global") -> dict[str, Any]:
        """Convenience method returning the settings dictionary."""
        _, settings = await self.get_state()
        gid = str(guild_id)
        guild_cfg = settings.get(gid, {})
        return {
            "badwords_enabled": guild_cfg.get("badwords_enabled", False),
            "links_enabled": guild_cfg.get("links_enabled", False),
            "invites_enabled": guild_cfg.get("invites_enabled", False),
            "spam_enabled": guild_cfg.get("spam_enabled", False),
            "caps_enabled": guild_cfg.get("caps_enabled", False),
            "bad_words": guild_cfg.get("bad_words", []),
        }

    async def set_filter_enabled(self, guild_id: int | str, filter_key: str, enabled: bool) -> None:
        offenses, settings = await self.get_state()
        gid = str(guild_id)
        if gid not in settings:
            settings[gid] = {}
        settings[gid][filter_key] = enabled
        await self.save_state(offenses, settings)

    async def add_bad_words(self, guild_id: int | str, words: list[str]) -> None:
        offenses, settings = await self.get_state()
        gid = str(guild_id)
        if gid not in settings:
            settings[gid] = {}
        current = set(settings[gid].get("bad_words", []))
        current.update(w.lower() for w in words)
        settings[gid]["bad_words"] = sorted(current)
        await self.save_state(offenses, settings)

    async def save_state(self, offenses: dict[str, Any], settings: dict[str, Any]) -> None:
        """Upsert offenses and settings to SQLite."""
        conn = await self.connect()
        payload = {"offenses": offenses, "settings": settings}
        await conn.execute(
            """
            INSERT INTO guild_settings (guild_id, section, data, updated_at)
            VALUES ('global', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, section) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (self.SECTION, self.dumps(payload)),
        )
        await conn.commit()


    async def _try_legacy_migration(self) -> dict[str, Any] | None:
        if config.MONGO_URI:
            try:
                import motor.motor_asyncio
                client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=2000)
                doc = await client["server_builder_bot"]["automod_state"].find_one({"_id": "global"})
                if doc:
                    return {"offenses": doc.get("offenses", {}), "settings": doc.get("settings", {})}
            except Exception as exc:
                log.debug("MongoDB legacy AutoMod migration skipped: %s", exc)

        if os.path.exists(config.AUTOMOD_FILE):
            try:
                with open(config.AUTOMOD_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "offenses" in data or "settings" in data:
                    return {"offenses": data.get("offenses", {}), "settings": data.get("settings", {})}
                return {"offenses": data, "settings": {}}
            except Exception:
                pass

        return None
