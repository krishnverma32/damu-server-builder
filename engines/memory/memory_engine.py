"""Memory Engine — Persists server preferences, build history, and managed resource bindings."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import aiofiles

import config

log = logging.getLogger("engines.memory")

MEMORY_STORE_FILE = os.path.join(config.DATA_DIR, "memory", "guild_memory.json")
FORBIDDEN_SECRET_KEYS = {"token", "secret", "password", "api_key", "mongo_uri"}


class MemoryEngine:
    """Stores non-sensitive guild preferences, build history, and managed IDs."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if os.path.exists(MEMORY_STORE_FILE):
            try:
                async with aiofiles.open(MEMORY_STORE_FILE, "r", encoding="utf-8") as f:
                    content = await f.read()
                    self._cache = json.loads(content) if content.strip() else {}
            except Exception as e:
                log.warning("Could not read guild memory file: %s", e)
                self._cache = {}
        self._loaded = True

    async def _save(self) -> None:
        os.makedirs(os.path.dirname(MEMORY_STORE_FILE), exist_ok=True)
        async with aiofiles.open(MEMORY_STORE_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(self._cache, indent=2))

    def _sanitize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Never allow tokens, passwords, or api keys into persistent guild memory."""
        clean = {}
        for k, v in data.items():
            if str(k).lower() in FORBIDDEN_SECRET_KEYS:
                continue
            if isinstance(v, dict):
                clean[k] = self._sanitize(v)
            else:
                clean[k] = v
        return clean

    async def get_guild_memory(self, guild_id: int) -> dict[str, Any]:
        await self._ensure_loaded()
        return self._cache.get(str(guild_id), {})

    async def set_guild_preference(self, guild_id: int, key: str, value: Any) -> None:
        if str(key).lower() in FORBIDDEN_SECRET_KEYS:
            raise ValueError(f"Security error: '{key}' cannot be saved in guild memory.")

        await self._ensure_loaded()
        gid = str(guild_id)
        if gid not in self._cache:
            self._cache[gid] = {}
        self._cache[gid][key] = value
        await self._save()

    async def record_build(self, guild_id: int, build_record: dict[str, Any]) -> None:
        """Append a completed build to the guild's build history (capped at 20)."""
        await self._ensure_loaded()
        gid = str(guild_id)
        if gid not in self._cache:
            self._cache[gid] = {}

        history = self._cache[gid].setdefault("build_history", [])
        clean_record = self._sanitize(build_record)
        history.append(clean_record)
        if len(history) > 20:
            self._cache[gid]["build_history"] = history[-20:]
        await self._save()


memory_engine = MemoryEngine()
