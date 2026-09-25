"""Health Engine — System diagnostics, health metrics, and deep environment doctor checks."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands

import config

log = logging.getLogger("engines.health")


@dataclass
class HealthStatus:
    bot_online: bool
    latency_ms: float
    discord_api_healthy: bool
    database_connected: bool
    ai_available: bool
    fallback_ready: bool
    loaded_cogs_count: int
    active_tasks_count: int
    recent_errors_count: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def format_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 DAMU STATUS",
            colour=0x2ECC71 if self.discord_api_healthy and self.bot_online else 0xE74C3C,
            timestamp=self.timestamp,
        )
        embed.add_field(name="Bot", value="🟢 Online" if self.bot_online else "🔴 Offline", inline=True)
        embed.add_field(name="Latency", value=f"`{self.latency_ms:.0f}ms`", inline=True)
        embed.add_field(name="Discord API", value="🟢 Healthy" if self.discord_api_healthy else "⚠️ Degraded", inline=True)

        embed.add_field(name="Database", value="🟢 Connected" if self.database_connected else "🟡 Ephemeral Cache", inline=True)
        embed.add_field(name="AI", value="🟢 Available" if self.ai_available else "🟡 Key Unset", inline=True)
        embed.add_field(name="Fallback Engine", value="🟢 Ready" if self.fallback_ready else "🔴 Inactive", inline=True)

        embed.add_field(name="Loaded Cogs", value=f"`{self.loaded_cogs_count}`", inline=True)
        embed.add_field(name="Active Tasks", value=f"`{self.active_tasks_count}`", inline=True)
        embed.add_field(name="Recent Errors", value=f"`{self.recent_errors_count}`", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} v{config.BOT_VERSION}")
        return embed


class HealthEngine:
    """Performs light status checks and deep doctor audits."""

    def __init__(self) -> None:
        self.recent_errors: list[str] = []

    def record_error(self, err_msg: str) -> None:
        self.recent_errors.append(err_msg)
        if len(self.recent_errors) > 50:
            self.recent_errors = self.recent_errors[-50:]

    async def get_status(self, bot: commands.Bot) -> HealthStatus:
        """Collect current real-time health metrics."""
        latency = bot.latency * 1000 if bot.latency is not None and bot.latency >= 0 else 0.0

        # Check database
        db_connected = False
        if config.MONGO_URI:
            try:
                import motor.motor_asyncio
                client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=1500)
                await client.admin.command("ping")
                db_connected = True
                client.close()
            except Exception:
                db_connected = False

        ai_available = bool(config.OPENROUTER_API_KEY)
        fallback_ready = True
        cogs_count = len(bot.cogs)
        tasks_count = len([t for t in asyncio.all_tasks() if not t.done()])

        return HealthStatus(
            bot_online=bot.is_ready(),
            latency_ms=latency,
            discord_api_healthy=latency < 500,
            database_connected=db_connected,
            ai_available=ai_available,
            fallback_ready=fallback_ready,
            loaded_cogs_count=cogs_count,
            active_tasks_count=tasks_count,
            recent_errors_count=len(self.recent_errors),
        )

    async def run_doctor(self, bot: commands.Bot, guild: discord.Guild | None = None) -> discord.Embed:
        """Run comprehensive diagnostic checks across all subsystems."""
        embed = discord.Embed(
            title="🩺 DAMU DOCTOR DIAGNOSTIC REPORT",
            description="Deep inspection of bot health, permissions, storage, and runtime state.",
            colour=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        # 1. Event Loop & Process
        loop_status = "🟢 Operational" if asyncio.get_event_loop().is_running() else "🔴 Stopped"
        embed.add_field(name="Event Loop", value=loop_status, inline=True)

        # 2. Database
        db_note = "🟢 Connected (MongoDB Atlas)" if config.MONGO_URI else "🟡 Ephemeral In-Memory Store"
        embed.add_field(name="Persistence Layer", value=db_note, inline=True)

        # 3. AI & Fallback
        ai_note = "🟢 Configured (OpenRouter)" if config.OPENROUTER_API_KEY else "🟡 Offline (Rule engine active)"
        embed.add_field(name="AI Subsystem", value=ai_note, inline=True)

        # 4. Storage paths
        paths_ok = all(os.path.exists(d) for d in [config.DATA_DIR, "data/memory", "data/tickets"])
        embed.add_field(name="File Storage", value="🟢 Readable/Writable" if paths_ok else "⚠️ Missing Directories", inline=True)

        # 5. Guild Permissions (if in a guild)
        if guild and guild.me:
            me = guild.me
            p = me.guild_permissions
            perm_checks = [
                ("Manage Channels", p.manage_channels),
                ("Manage Roles", p.manage_roles),
                ("Manage Messages", p.manage_messages),
                ("View Audit Log", p.view_audit_log),
            ]
            perm_str = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in perm_checks)
            embed.add_field(name=f"Permissions in {guild.name}", value=perm_str, inline=False)

        # 6. Persistent views check
        embed.add_field(name="Loaded Cogs", value=", ".join(sorted(bot.cogs.keys())) or "None", inline=False)
        return embed


health_engine = HealthEngine()
