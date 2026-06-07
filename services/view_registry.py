"""Persistent Discord UI view registry."""

from __future__ import annotations

import json
import logging
from typing import Any

import discord
from discord.ext import commands

from services.database import get_database

log = logging.getLogger("services.view_registry")


class ViewRegistry:
    """Stores persistent view metadata and restores known view handlers."""

    def __init__(self) -> None:
        self.db = get_database()
        self._views: dict[str, discord.ui.View] = {}
        self._registered_types: set[str] = set()
        self._restored = False

    @staticmethod
    def _view_type(view: discord.ui.View) -> str:
        name = view.__class__.__name__
        if name == "TicketPanelView":
            return "ticket_panel"
        if name == "TicketControlView":
            return "ticket_control"
        return name

    async def add_runtime_view(
        self,
        bot: commands.Bot,
        view_id: str,
        view: discord.ui.View,
        view_type: str | None = None,
    ) -> bool:
        resolved_type = view_type or self._view_type(view)
        self._views[view_id] = view
        if resolved_type in self._registered_types:
            return False
        bot.add_view(view)
        self._registered_types.add(resolved_type)
        return True

    async def register(
        self,
        view_id: str,
        view: discord.ui.View,
        data: dict[str, Any] | None = None,
        view_type: str | None = None,
    ) -> None:
        resolved_type = view_type or self._view_type(view)
        self._views[view_id] = view
        conn = await self.db.connect()
        await conn.execute(
            """
            INSERT INTO persistent_views (view_id, view_type, data, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(view_id) DO UPDATE SET
                view_type = excluded.view_type,
                data = excluded.data
            """,
            (view_id, resolved_type, json.dumps(data or {})),
        )
        await conn.commit()

    async def unregister(self, view_id: str) -> None:
        self._views.pop(view_id, None)
        conn = await self.db.connect()
        await conn.execute("DELETE FROM persistent_views WHERE view_id = ?", (view_id,))
        await conn.commit()

    async def restore_all(self, bot: commands.Bot) -> int:
        if self._restored:
            return 0

        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT view_id, view_type, data
            FROM persistent_views
            ORDER BY created_at ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()

        restored = 0
        for row in rows:
            view_id = row["view_id"]
            view_type = row["view_type"]
            try:
                view = self._build_view(view_type)
                if view is None:
                    log.warning("Unknown persistent view type %s for %s", view_type, view_id)
                    continue
                added = await self.add_runtime_view(bot, view_id, view, view_type)
                restored += 1 if added else 0
            except Exception as exc:
                log.warning("Could not restore persistent view %s: %s", view_id, exc)

        self._restored = True
        return restored

    def _build_view(self, view_type: str) -> discord.ui.View | None:
        if view_type == "ticket_panel":
            from cogs.ticket_system import TicketPanelView

            return TicketPanelView()
        if view_type == "ticket_control":
            from cogs.ticket_system import TicketControlView

            return TicketControlView()
        return None
