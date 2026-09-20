"""Base repository with shared async SQLite helpers."""

from __future__ import annotations

import json
from typing import Any

from services.database import Database, get_database


class BaseRepository:
    """Base class for all SQLite-backed domain repositories."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or get_database()

    async def connect(self):
        return await self.db.connect()

    @staticmethod
    def dumps(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def loads(raw: str | None, default: Any = None) -> Any:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default
