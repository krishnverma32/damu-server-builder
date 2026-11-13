"""Embed factory — consistent colour-coded embeds for every response."""

from __future__ import annotations

import datetime

import discord

import config

# ── Colour palette ────────────────────────────────────────────────────────────────
_GREEN = 0x57F287
_RED = 0xED4245
_BLUE = 0x5865F2
_ORANGE = 0xFEE75C


def _base(title: str, description: str, colour: int) -> discord.Embed:
    em = discord.Embed(
        title=title,
        description=description,
        colour=colour,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    em.set_footer(text=f"{config.BOT_NAME} v{config.BOT_VERSION} • Created by {config.BOT_CREATOR_NAME}")
    return em


def success_embed(title: str, description: str) -> discord.Embed:
    return _base(title, description, _GREEN)


def error_embed(title: str, description: str) -> discord.Embed:
    return _base(title, description, _RED)


def info_embed(title: str, description: str) -> discord.Embed:
    return _base(title, description, _BLUE)


def warning_embed(title: str, description: str) -> discord.Embed:
    return _base(title, description, _ORANGE)
