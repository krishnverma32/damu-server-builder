"""SQLite-backed Build History Repository for tracking builds and enabling rollback."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.build")


class BuildRepository(BaseRepository):
    """Stores build operations, created resources, and rollback state in SQLite."""

    async def create_build(
        self,
        guild_id: int,
        user_id: int,
        template: str = "",
        schema_version: str = "2.0",
        plan_dict: dict[str, Any] | None = None,
    ) -> int:
        """Create a new build record with status 'running' and return its integer build_id."""
        conn = await self.connect()
        cursor = await conn.execute(
            """
            INSERT INTO build_history (
                guild_id, user_id, template, schema_version, status,
                created_resources, modified_resources, deleted_resources, errors,
                plan_json, created_at
            )
            VALUES (?, ?, ?, ?, 'running', '[]', '[]', '[]', '[]', ?, CURRENT_TIMESTAMP)
            """,
            (
                str(guild_id),
                str(user_id),
                template,
                schema_version,
                self.dumps(plan_dict or {}),
            ),
        )
        await conn.commit()
        return cursor.lastrowid

    async def complete_build(
        self,
        build_id: int,
        status: str,
        created_resources: list[int] | None = None,
        modified_resources: list[str] | None = None,
        deleted_resources: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        """Update build upon completion or failure."""
        conn = await self.connect()
        await conn.execute(
            """
            UPDATE build_history
            SET status = ?,
                created_resources = ?,
                modified_resources = ?,
                deleted_resources = ?,
                errors = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE build_id = ?
            """,
            (
                status,
                self.dumps(created_resources or []),
                self.dumps(modified_resources or []),
                self.dumps(deleted_resources or []),
                self.dumps(errors or []),
                build_id,
            ),
        )
        await conn.commit()

    async def get_build(self, build_id: int) -> dict[str, Any] | None:
        """Retrieve a specific build record."""
        conn = await self.connect()
        async with conn.execute(
            """
            SELECT build_id, guild_id, user_id, template, schema_version, status,
                   created_resources, modified_resources, deleted_resources, errors,
                   plan_json, created_at, completed_at
            FROM build_history
            WHERE build_id = ?
            """,
            (build_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "build_id": row["build_id"],
            "guild_id": int(row["guild_id"]),
            "user_id": int(row["user_id"]),
            "template": row["template"],
            "schema_version": row["schema_version"],
            "status": row["status"],
            "created_resources": self.loads(row["created_resources"], []),
            "modified_resources": self.loads(row["modified_resources"], []),
            "deleted_resources": self.loads(row["deleted_resources"], []),
            "errors": self.loads(row["errors"], []),
            "plan_json": self.loads(row["plan_json"], {}),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    async def list_builds(self, guild_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """List the most recent builds for a guild."""
        conn = await self.connect()
        async with conn.execute(
            """
            SELECT build_id, guild_id, user_id, template, schema_version, status,
                   created_resources, modified_resources, deleted_resources, errors,
                   created_at, completed_at
            FROM build_history
            WHERE guild_id = ?
            ORDER BY build_id DESC
            LIMIT ?
            """,
            (str(guild_id), limit),
        ) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                "build_id": row["build_id"],
                "guild_id": int(row["guild_id"]),
                "user_id": int(row["user_id"]),
                "template": row["template"],
                "schema_version": row["schema_version"],
                "status": row["status"],
                "created_resources": self.loads(row["created_resources"], []),
                "modified_resources": self.loads(row["modified_resources"], []),
                "deleted_resources": self.loads(row["deleted_resources"], []),
                "errors": self.loads(row["errors"], []),
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
            })
        return results

    async def mark_rolled_back(self, build_id: int) -> None:
        """Mark a build as rolled_back."""
        conn = await self.connect()
        await conn.execute(
            "UPDATE build_history SET status = 'rolled_back', completed_at = CURRENT_TIMESTAMP WHERE build_id = ?",
            (build_id,),
        )
        await conn.commit()

    record_rollback = mark_rolled_back

