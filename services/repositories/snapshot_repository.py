"""SQLite-backed Snapshot Repository for server backups and restores."""

from __future__ import annotations

import logging
from typing import Any

from services.repositories.base import BaseRepository

log = logging.getLogger("repositories.snapshot")


class SnapshotRepository(BaseRepository):
    """Manages versioned server layout snapshots in SQLite."""

    async def create_snapshot(
        self,
        guild_id: int,
        user_id: int,
        name: str,
        data: dict[str, Any],
        version: str = "2.0",
    ) -> int:
        """Create a new snapshot and return an integer snapshot_id."""
        import time
        snap_id = int(time.time() * 1000) % 1_000_000
        await self.save_snapshot(
            snapshot_id=str(snap_id),
            guild_id=guild_id,
            name=name,
            data=data,
            version=version,
        )
        return snap_id

    async def save_snapshot(
        self,
        snapshot_id: str,
        guild_id: int,
        name: str,
        data: dict[str, Any],
        version: str = "2.0",
    ) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            INSERT INTO snapshots (snapshot_id, guild_id, name, version, data, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                name = excluded.name,
                version = excluded.version,
                data = excluded.data,
                created_at = CURRENT_TIMESTAMP
            """,
            (str(snapshot_id), str(guild_id), name, version, self.dumps(data)),
        )
        await conn.commit()

    async def get_snapshot(self, snapshot_id: str | int) -> dict[str, Any] | None:
        conn = await self.connect()
        async with conn.execute(
            """
            SELECT snapshot_id, guild_id, name, version, data, created_at
            FROM snapshots
            WHERE snapshot_id = ?
            """,
            (str(snapshot_id),),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return {
            "snapshot_id": row["snapshot_id"],
            "guild_id": int(row["guild_id"]),
            "name": row["name"],
            "version": row["version"],
            "data": self.loads(row["data"], {}),
            "created_at": row["created_at"],
        }

    async def list_snapshots(self, guild_id: int, limit: int = 20) -> list[dict[str, Any]]:
        conn = await self.connect()
        async with conn.execute(
            """
            SELECT snapshot_id, guild_id, name, version, created_at
            FROM snapshots
            WHERE guild_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(guild_id), limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "snapshot_id": row["snapshot_id"],
                "guild_id": int(row["guild_id"]),
                "name": row["name"],
                "version": row["version"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def delete_snapshot(self, snapshot_id: str) -> bool:
        conn = await self.connect()
        cursor = await conn.execute(
            "DELETE FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        await conn.commit()
        return cursor.rowcount > 0
