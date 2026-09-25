"""Audit Engine — Records structured change audit trails for all operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import discord

from core.logging import log_event, sanitize_data

log = logging.getLogger("engines.audit")


@dataclass
class AuditEntry:
    who: str
    user_id: int
    what: str
    action_type: str
    where: str
    guild_id: int
    result: str  # Success / Failed / Rolled Back
    build_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "who": self.who,
            "user_id": self.user_id,
            "what": self.what,
            "action_type": self.action_type,
            "where": self.where,
            "guild_id": self.guild_id,
            "result": self.result,
            "build_id": self.build_id,
            "timestamp": self.timestamp.isoformat(),
            "details": sanitize_data(self.details),
        }

    def format_embed(self) -> discord.Embed:
        color = 0x2ECC71 if self.result == "Success" else 0xE74C3C
        embed = discord.Embed(
            title="🛡️ DAMU AUDIT RECORD",
            description=f"**Action:** {self.what}",
            colour=color,
            timestamp=self.timestamp,
        )
        embed.add_field(name="Actor", value=f"{self.who} (`{self.user_id}`)", inline=True)
        embed.add_field(name="Target / Location", value=self.where, inline=True)
        embed.add_field(name="Result", value=self.result, inline=True)
        if self.build_id:
            embed.set_footer(text=f"Transaction: {self.build_id}")
        return embed


class AuditEngine:
    """Manages audit log retention and dispatch to Discord mod-log channels."""

    def __init__(self) -> None:
        self._recent_logs: list[AuditEntry] = []

    async def record_event(
        self,
        actor: discord.User | discord.Member,
        guild: discord.Guild,
        action_name: str,
        target_name: str,
        action_type: str,
        result: str = "Success",
        build_id: str | None = None,
        details: dict[str, Any] | None = None,
        mod_log_channel: discord.TextChannel | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            who=str(actor),
            user_id=actor.id,
            what=action_name,
            action_type=action_type,
            where=f"{guild.name} -> {target_name}",
            guild_id=guild.id,
            result=result,
            build_id=build_id,
            details=details or {},
        )
        self._recent_logs.append(entry)
        if len(self._recent_logs) > 100:
            self._recent_logs = self._recent_logs[-100:]

        # Structured log
        log_event(
            "audit_record",
            guild_id=guild.id,
            user_id=actor.id,
            action=action_name,
            target=target_name,
            result=result,
            build_id=build_id,
        )

        # Dispatch embed to mod log channel if configured
        if mod_log_channel:
            try:
                await mod_log_channel.send(embed=entry.format_embed())
            except Exception as e:
                log.warning("Could not send audit embed to mod log channel: %s", e)

        return entry


audit_engine = AuditEngine()
