"""Context data models for intelligence planning and prompt generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import discord


@dataclass
class IntelligenceContext:
    guild: discord.Guild
    user: discord.User | discord.Member
    raw_prompt: str
    channel_count: int = 0
    role_count: int = 0
    recent_intents: list[str] = field(default_factory=list)

    @classmethod
    def from_guild(cls, guild: discord.Guild, user: discord.User | discord.Member, prompt: str) -> IntelligenceContext:
        return cls(
            guild=guild,
            user=user,
            raw_prompt=prompt,
            channel_count=len(guild.channels),
            role_count=len(guild.roles),
        )
