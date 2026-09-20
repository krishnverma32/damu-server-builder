"""SQLite-backed Guild Settings Repository for Dashboard, Verification, and Bypass IDs."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import config
from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.guild")


class GuildRepository(BaseRepository):
    """Manages dashboard, verification, and server configuration settings in SQLite."""

    DASHBOARD_SECTION = "dashboard_config"
    VERIFICATION_SECTION = "verification_config"
    BYPASS_SECTION = "builder_bypass_ids"

    async def get_dashboard_config(self, guild_id: int) -> dict[str, Any]:
        conn = await self.connect()
        async with conn.execute(
            "SELECT data FROM guild_settings WHERE guild_id = ? AND section = ?",
            (str(guild_id), self.DASHBOARD_SECTION),
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            return self.loads(row["data"], {})

        # Migrate from legacy DASHBOARD_CONFIG_FILE if available
        if os.path.exists(config.DASHBOARD_CONFIG_FILE):
            try:
                with open(config.DASHBOARD_CONFIG_FILE, "r", encoding="utf-8") as f:
                    all_cfg = json.load(f)
                if str(guild_id) in all_cfg:
                    cfg = all_cfg[str(guild_id)]
                    await self.save_dashboard_config(guild_id, cfg)
                    return cfg
            except Exception:
                pass

        return {}

    async def save_dashboard_config(self, guild_id: int, data: dict[str, Any]) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            INSERT INTO guild_settings (guild_id, section, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, section) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(guild_id), self.DASHBOARD_SECTION, self.dumps(data)),
        )
        await conn.commit()

    async def get_verification_config(self, guild_id: int) -> dict[str, Any]:
        conn = await self.connect()
        async with conn.execute(
            "SELECT data FROM guild_settings WHERE guild_id = ? AND section = ?",
            (str(guild_id), self.VERIFICATION_SECTION),
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            return self.loads(row["data"], {})

        # Migrate from legacy VERIFICATION_CONFIG_FILE
        if os.path.exists(config.VERIFICATION_CONFIG_FILE):
            try:
                with open(config.VERIFICATION_CONFIG_FILE, "r", encoding="utf-8") as f:
                    all_cfg = json.load(f)
                if str(guild_id) in all_cfg:
                    cfg = all_cfg[str(guild_id)]
                    await self.save_verification_config(guild_id, cfg)
                    return cfg
            except Exception:
                pass

        return {}

    async def save_verification_config(self, guild_id: int, data: dict[str, Any]) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            INSERT INTO guild_settings (guild_id, section, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, section) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(guild_id), self.VERIFICATION_SECTION, self.dumps(data)),
        )
        await conn.commit()

    async def get_builder_bypass_ids(self) -> set[int]:
        conn = await self.connect()
        async with conn.execute(
            "SELECT data FROM guild_settings WHERE guild_id = 'global' AND section = ?",
            (self.BYPASS_SECTION,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            return set(self.loads(row["data"], []))

        # Migrate from server_builder_bypass.json if exists
        bypass_file = f"{config.DATA_DIR}/server_builder_bypass.json"
        if os.path.exists(bypass_file):
            try:
                with open(bypass_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                uids = set(data if isinstance(data, list) else [])
                await self.save_builder_bypass_ids(uids)
                return uids
            except Exception:
                pass

        # Default to config.SERVER_BUILD_BYPASS_IDS
        return set(config.SERVER_BUILD_BYPASS_IDS)

    async def save_builder_bypass_ids(self, ids: set[int]) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            INSERT INTO guild_settings (guild_id, section, data, updated_at)
            VALUES ('global', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, section) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (self.BYPASS_SECTION, self.dumps(sorted(ids))),
        )
        await conn.commit()
