"""Async SQLite storage helpers for bot state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import aiosqlite

import config


class Database:
    """Small async SQLite wrapper for namespaced JSON records."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or getattr(config, "DATABASE_FILE", f"{config.DATA_DIR}/bot.db")
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            Path(os.path.dirname(self.path)).mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._conn.commit()
        return self._conn

    async def create_tables(self) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_store (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_memory (
                user_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_usage (
                guild_id TEXT NOT NULL DEFAULT '0',
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id, date)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS levels (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                data TEXT NOT NULL,
                open INTEGER NOT NULL DEFAULT 0,
                channel_id TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS persistent_views (
                view_id TEXT PRIMARY KEY,
                view_type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                guild_id TEXT NOT NULL,
                date TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, date)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT NOT NULL,
                section TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, section)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS build_history (
                build_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                template TEXT NOT NULL DEFAULT '',
                schema_version TEXT NOT NULL DEFAULT '2.0',
                status TEXT NOT NULL DEFAULT 'running',
                created_resources TEXT NOT NULL DEFAULT '[]',
                modified_resources TEXT NOT NULL DEFAULT '[]',
                deleted_resources TEXT NOT NULL DEFAULT '[]',
                errors TEXT NOT NULL DEFAULT '[]',
                plan_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '2.0',
                data TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS moderation_warnings (
                warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                mod_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.commit()

    async def get(self, namespace: str, key: str, default: Any = None) -> Any:
        conn = await self.connect()
        async with conn.execute(
            "SELECT value FROM kv_store WHERE namespace = ? AND key = ?",
            (namespace, key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    async def set(self, namespace: str, key: str, value: Any) -> None:
        conn = await self.connect()
        await conn.execute(
            """
            INSERT INTO kv_store (namespace, key, value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(namespace, key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (namespace, key, json.dumps(value)),
        )
        await conn.commit()

    async def delete(self, namespace: str, key: str) -> None:
        conn = await self.connect()
        await conn.execute(
            "DELETE FROM kv_store WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        await conn.commit()

    async def list_keys(self, namespace: str) -> list[str]:
        conn = await self.connect()
        async with conn.execute(
            "SELECT key FROM kv_store WHERE namespace = ? ORDER BY key",
            (namespace,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["key"] for row in rows]

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


_database = Database()


def get_database() -> Database:
    return _database
