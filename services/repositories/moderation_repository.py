"""SQLite-backed Moderation Repository for user warnings and audit logs."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import config
from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.moderation")


class ModerationRepository(BaseRepository):
    """Stores warnings and audit logs in SQLite."""

    async def add_warning(self, guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
        conn = await self.connect()
        cursor = await conn.execute(
            """
            INSERT INTO moderation_warnings (guild_id, user_id, mod_id, reason, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (str(guild_id), str(user_id), str(mod_id), reason),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_warnings(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        conn = await self.connect()
        async with conn.execute(
            """
            SELECT warning_id, mod_id, reason, created_at
            FROM moderation_warnings
            WHERE guild_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            (str(guild_id), str(user_id)),
        ) as cursor:
            rows = await cursor.fetchall()

        if rows:
            return [
                {
                    "warning_id": row["warning_id"],
                    "mod_id": int(row["mod_id"]),
                    "reason": row["reason"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

        # Check legacy migration from WARNINGS_FILE
        migrated = await self._try_legacy_migration(guild_id, user_id)
        return migrated

    async def clear_warnings(self, guild_id: int, user_id: int) -> int:
        conn = await self.connect()
        cursor = await conn.execute(
            "DELETE FROM moderation_warnings WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id)),
        )
        await conn.commit()
        return cursor.rowcount

    async def log_audit(
        self,
        guild_id: int,
        action: str,
        target_type: str = "",
        target_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> int:
        conn = await self.connect()
        cursor = await conn.execute(
            """
            INSERT INTO audit_logs (guild_id, action, target_type, target_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (str(guild_id), action, target_type, target_id, self.dumps(details or {})),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_audit_logs(self, guild_id: int, limit: int = 50) -> list[dict[str, Any]]:
        conn = await self.connect()
        async with conn.execute(
            """
            SELECT audit_id, action, target_type, target_id, details, created_at
            FROM audit_logs
            WHERE guild_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(guild_id), limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "audit_id": row["audit_id"],
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "details": self.loads(row["details"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def _try_legacy_migration(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        if os.path.exists(config.WARNINGS_FILE):
            try:
                with open(config.WARNINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                key = f"{guild_id}_{user_id}"
                if key in data:
                    warnings = data[key]
                    conn = await self.connect()
                    for w in warnings:
                        await conn.execute(
                            """
                            INSERT INTO moderation_warnings (guild_id, user_id, mod_id, reason, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                str(guild_id),
                                str(user_id),
                                str(w.get("mod_id", 0)),
                                w.get("reason", "No reason provided"),
                                w.get("timestamp") or "2026-01-01 00:00:00",
                            ),
                        )
                    await conn.commit()
                    return warnings
            except Exception:
                pass
        return []
