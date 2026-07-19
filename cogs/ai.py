"""AI chat cog with cooldowns, daily budgets, and guild controls."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from services import ai_service
from services.database import get_database
from services.embed_service import error_embed, info_embed, success_embed
from services.report_service import record_counter
from utils.helpers import chunk_text

log = logging.getLogger("cogs.ai")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _next_midnight_timestamp() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return int(tomorrow.timestamp())


def _estimate_tokens(prompt: str, reply: str = "") -> int:
    words = len(prompt.split()) + len(reply.split())
    return max(1, int(words * 1.3))


def _enabled_key(guild_id: int) -> str:
    return f"ai_enabled:{guild_id}"


class AICog(commands.Cog, name="AI"):
    """AI chat with per-user memory, spend limits, and server controls."""

    ai = app_commands.Group(name="ai", description="AI assistant commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = get_database()

    async def _is_owner(self, user: discord.abc.User) -> bool:
        return await self.bot.is_owner(user)

    async def _ai_enabled(self, guild_id: int | None) -> bool:
        if guild_id is None:
            return True
        return bool(await self.db.get("guild_settings", _enabled_key(guild_id), True))

    async def _set_ai_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.db.set("guild_settings", _enabled_key(guild_id), enabled)

    async def _user_tokens_today(self, user_id: int) -> int:
        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT COALESCE(SUM(tokens_used), 0) AS total
            FROM ai_usage
            WHERE user_id = ? AND date = ?
            """,
            (str(user_id), _today()),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["total"] or 0)

    async def _global_tokens_today(self) -> int:
        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT COALESCE(SUM(tokens_used), 0) AS total
            FROM ai_usage
            WHERE date = ?
            """,
            (_today(),),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["total"] or 0)

    async def _guild_usage_today(self, guild_id: int) -> tuple[int, int]:
        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT COALESCE(SUM(tokens_used), 0) AS total,
                   COUNT(DISTINCT user_id) AS users
            FROM ai_usage
            WHERE guild_id = ? AND date = ?
            """,
            (str(guild_id), _today()),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["total"] or 0), int(row["users"] or 0)

    async def _add_usage(self, guild_id: int | None, user_id: int, tokens: int) -> None:
        conn = await self.db.connect()
        await conn.execute(
            """
            INSERT INTO ai_usage (guild_id, user_id, date, tokens_used, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, user_id, date) DO UPDATE SET
                tokens_used = tokens_used + excluded.tokens_used,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(guild_id or 0), str(user_id), _today(), max(0, tokens)),
        )
        await conn.commit()

    async def _notify_owner_global_limit(self) -> None:
        key = f"ai_global_limit_notice:{_today()}"
        if await self.db.get("ai_notices", key, False):
            return

        owner_id = getattr(config, "BOT_OWNER_ID", 0)
        owner = self.bot.get_user(owner_id) if owner_id else None
        if owner is None and owner_id:
            try:
                owner = await self.bot.fetch_user(owner_id)
            except discord.HTTPException:
                owner = None

        if owner:
            try:
                await owner.send(
                    embed=error_embed(
                        "AI Daily Limit Hit",
                        f"The bot reached **{config.AI_DAILY_TOKEN_LIMIT:,}** AI tokens today. "
                        f"AI chat is disabled until midnight UTC.",
                    )
                )
            except discord.HTTPException:
                log.warning("Could not DM owner about AI daily limit.")

        await self.db.set("ai_notices", key, True)

    async def _send_limit_message(self, interaction: discord.Interaction, title: str, description: str) -> None:
        embed = error_embed(title, f"{description}\nResets <t:{_next_midnight_timestamp()}:R>.")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai.command(name="chat", description="Chat with the AI assistant.")
    @app_commands.describe(prompt="Your message to the AI")
    @app_commands.checks.cooldown(rate=3, per=60.0)
    async def chat(self, interaction: discord.Interaction, prompt: str) -> None:
        owner = await self._is_owner(interaction.user)
        guild_id = interaction.guild_id

        if not await self._ai_enabled(guild_id):
            await interaction.response.send_message(
                embed=error_embed("AI Disabled", "AI commands are disabled in this server."),
                ephemeral=True,
            )
            return

        if not owner:
            prompt_estimate = _estimate_tokens(prompt)
            user_used = await self._user_tokens_today(interaction.user.id)
            if user_used + prompt_estimate > config.AI_USER_DAILY_LIMIT:
                await self._send_limit_message(
                    interaction,
                    "Daily AI Limit",
                    f"You have used **{user_used:,}/{config.AI_USER_DAILY_LIMIT:,}** tokens today.",
                )
                return

            global_used = await self._global_tokens_today()
            if global_used + prompt_estimate > config.AI_DAILY_TOKEN_LIMIT:
                await self._notify_owner_global_limit()
                await self._send_limit_message(
                    interaction,
                    "AI Paused",
                    f"The bot has used **{global_used:,}/{config.AI_DAILY_TOKEN_LIMIT:,}** tokens today.",
                )
                return

        await interaction.response.defer(thinking=True)

        result = await ai_service.get_ai_response(
            prompt,
            interaction.user.id,
            guild_id=interaction.guild_id,
            username=interaction.user.display_name,
            return_usage=True,
        )
        reply, reported_tokens = result if isinstance(result, tuple) else (result, 0)
        tokens_used = reported_tokens or _estimate_tokens(prompt, reply)

        if not owner:
            await self._add_usage(guild_id, interaction.user.id, tokens_used)
            if guild_id is not None:
                await record_counter(guild_id, "ai", "messages")
            if await self._global_tokens_today() >= config.AI_DAILY_TOKEN_LIMIT:
                await self._notify_owner_global_limit()

        chunks = chunk_text(reply)
        await interaction.followup.send(content=chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(content=chunk)

    @ai.command(name="reset", description="Clear your AI conversation memory.")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def reset(self, interaction: discord.Interaction) -> None:
        await ai_service.reset_user_memory(interaction.user.id, interaction.guild_id)
        await interaction.response.send_message(
            embed=success_embed("Memory Cleared", "Your conversation history has been reset."),
            ephemeral=True,
        )

    @ai.command(name="persona", description="Switch the AI's personality.")
    @app_commands.describe(set="Persona name")
    @app_commands.choices(
        set=[
            app_commands.Choice(name="Default (helpful assistant)", value="default"),
            app_commands.Choice(name="Mentor (patient teacher)", value="mentor"),
            app_commands.Choice(name="Sarcastic (witty & dry)", value="sarcastic"),
            app_commands.Choice(name="Professional (formal)", value="professional"),
            app_commands.Choice(name="Coder (software engineer)", value="coder"),
            app_commands.Choice(name="Rukiya (live chat character)", value="rukiya"),
        ]
    )
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def persona(self, interaction: discord.Interaction, set: app_commands.Choice[str]) -> None:
        await ai_service.set_user_persona(interaction.user.id, set.value, interaction.guild_id)
        await interaction.response.send_message(
            embed=success_embed("Persona Updated", f"AI persona set to **{set.name}**."),
            ephemeral=True,
        )

    @ai.command(name="usage", description="Show your remaining daily AI token budget.")
    @app_commands.checks.cooldown(rate=5, per=60.0)
    async def usage(self, interaction: discord.Interaction) -> None:
        used = await self._user_tokens_today(interaction.user.id)
        remaining = max(0, config.AI_USER_DAILY_LIMIT - used)
        embed = info_embed(
            "AI Usage",
            f"Used today: **{used:,}** tokens\n"
            f"Remaining: **{remaining:,}** tokens\n"
            f"Resets <t:{_next_midnight_timestamp()}:R>.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai.command(name="stats", description="Show this server's AI usage today.")
    @app_commands.default_permissions(manage_guild=True)
    async def stats(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("Server Only", "Run this command inside a server."),
                ephemeral=True,
            )
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "You need Manage Server permission."),
                ephemeral=True,
            )
            return

        guild_tokens, users = await self._guild_usage_today(interaction.guild_id)
        global_tokens = await self._global_tokens_today()
        enabled = await self._ai_enabled(interaction.guild_id)
        embed = info_embed(
            "AI Stats",
            f"Server AI: **{'Enabled' if enabled else 'Disabled'}**\n"
            f"Server tokens today: **{guild_tokens:,}**\n"
            f"Active users today: **{users:,}**\n"
            f"Global tokens today: **{global_tokens:,}/{config.AI_DAILY_TOKEN_LIMIT:,}**",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai.command(name="toggle", description="Enable or disable AI commands for this server.")
    @app_commands.describe(enabled="True enables AI, False disables AI")
    @app_commands.default_permissions(manage_guild=True)
    async def toggle(self, interaction: discord.Interaction, enabled: bool) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                embed=error_embed("Server Only", "Run this command inside a server."),
                ephemeral=True,
            )
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "You need Manage Server permission."),
                ephemeral=True,
            )
            return

        await self._set_ai_enabled(interaction.guild_id, enabled)
        await interaction.response.send_message(
            embed=success_embed(
                "AI Updated",
                f"AI commands are now **{'enabled' if enabled else 'disabled'}** for this server.",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
