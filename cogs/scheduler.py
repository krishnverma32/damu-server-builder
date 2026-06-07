"""Scheduled maintenance and automation tasks."""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks
try:
    import psutil
except ImportError:  # pragma: no cover - dependency is installed from requirements in production
    psutil = None  # type: ignore[assignment]

import config
from services.database import get_database
from services.embed_service import error_embed, info_embed, success_embed, warning_embed
from services.level_service import get_leaderboard

log = logging.getLogger("cogs.scheduler")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_key(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).date().isoformat()


def _settings_key(name: str, guild_id: int) -> str:
    return f"{name}:{guild_id}"


class SchedulerCog(commands.Cog, name="Scheduler"):
    """Background tasks for reports, stale tickets, analytics, and leaderboards."""

    TASK_NAMES = {
        "daily_reset",
        "weekly_leaderboard",
        "stale_tickets",
        "health_report",
        "analytics_aggregation",
    }

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = get_database()

    async def cog_load(self) -> None:
        self.daily_reset.start()
        self.weekly_leaderboard.start()
        self.stale_ticket_scan.start()
        self.health_report.start()
        self.analytics_aggregation.start()

    async def cog_unload(self) -> None:
        self.daily_reset.cancel()
        self.weekly_leaderboard.cancel()
        self.stale_ticket_scan.cancel()
        self.health_report.cancel()
        self.analytics_aggregation.cancel()

    async def _owner_only(self, interaction: discord.Interaction) -> bool:
        if await self.bot.is_owner(interaction.user):
            return True
        await interaction.response.send_message(
            embed=error_embed("Owner Only", "You do not have permission to use this command."),
            ephemeral=True,
        )
        return False

    async def _announcement_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.db.get("guild_settings", _settings_key("announcement_channel", guild.id))
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _dm_owner(self, embed: discord.Embed) -> None:
        owner_id = getattr(config, "BOT_OWNER_ID", 0)
        owner = self.bot.get_user(owner_id) if owner_id else None
        if owner is None and owner_id:
            try:
                owner = await self.bot.fetch_user(owner_id)
            except discord.HTTPException:
                owner = None
        if owner is None:
            return
        try:
            await owner.send(embed=embed)
        except discord.HTTPException:
            log.warning("Could not send scheduler DM to bot owner.")

    async def _run_daily_reset(self) -> str:
        posted = 0
        for guild in self.bot.guilds:
            channel = await self._announcement_channel(guild)
            if channel is None:
                continue
            try:
                await channel.send(
                    embed=success_embed(
                        "Daily Reset",
                        "Daily bot tasks have refreshed. Economy rewards are skipped because economy is disabled.",
                    )
                )
                posted += 1
            except discord.HTTPException as exc:
                log.warning("Daily reset announcement failed in %s: %s", guild.id, exc)
        return f"daily_reset complete; announcements={posted}"

    async def _run_weekly_leaderboard(self) -> str:
        posted = 0
        for guild in self.bot.guilds:
            channel = await self._announcement_channel(guild)
            if channel is None:
                continue

            leaderboard = await get_leaderboard(guild.id, limit=10)
            if not leaderboard:
                continue

            lines: list[str] = []
            for index, (user_id, xp, level) in enumerate(leaderboard, start=1):
                member = guild.get_member(user_id)
                name = member.display_name if member else f"User {user_id}"
                lines.append(f"**{index}.** {name} - `{xp}` XP, level `{level}`")

            try:
                await channel.send(embed=info_embed("Weekly XP Leaderboard", "\n".join(lines)))
                posted += 1
            except discord.HTTPException as exc:
                log.warning("Weekly leaderboard failed in %s: %s", guild.id, exc)
        return f"weekly_leaderboard complete; announcements={posted}"

    async def _run_stale_tickets(self) -> str:
        warned = 0
        closed = 0
        ticket_cog = self.bot.get_cog("TicketSystem")
        if ticket_cog is None or not hasattr(ticket_cog, "config_manager"):
            return "stale_tickets skipped; TicketSystem not loaded"

        now = _utc_now()
        for guild in self.bot.guilds:
            try:
                config_data = await ticket_cog.config_manager.get_guild(guild.id)  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("Could not load ticket config for %s: %s", guild.id, exc)
                continue

            open_tickets: dict[str, int] = dict(config_data.get("open_tickets", {}))
            if not open_tickets:
                continue

            changed = False
            for user_id_str, channel_id in list(open_tickets.items()):
                channel = guild.get_channel(int(channel_id))
                if not isinstance(channel, discord.TextChannel):
                    open_tickets.pop(user_id_str, None)
                    changed = True
                    continue

                try:
                    last_message = None
                    async for msg in channel.history(limit=1):
                        last_message = msg
                    last_activity = last_message.created_at if last_message else channel.created_at
                except discord.HTTPException:
                    continue

                age = now - last_activity
                warn_key = f"ticket_stale_warned:{guild.id}:{channel.id}"

                if age >= timedelta(hours=72):
                    await self._archive_ticket(guild, channel, int(user_id_str), open_tickets, config_data)
                    changed = True
                    closed += 1
                elif age >= timedelta(hours=48) and not await self.db.get("scheduler", warn_key, False):
                    try:
                        await channel.send(
                            embed=warning_embed(
                                "Ticket Inactivity",
                                "This ticket will be auto-closed in 24 hours due to inactivity.",
                            )
                        )
                        await self.db.set("scheduler", warn_key, True)
                        warned += 1
                    except discord.HTTPException as exc:
                        log.warning("Could not warn stale ticket %s: %s", channel.id, exc)

            if changed:
                config_data["open_tickets"] = open_tickets
                try:
                    await ticket_cog.config_manager.save_guild(guild.id, config_data)  # type: ignore[attr-defined]
                except Exception as exc:
                    log.warning("Could not save ticket config for %s: %s", guild.id, exc)

        return f"stale_tickets complete; warned={warned}, closed={closed}"

    async def _archive_ticket(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        user_id: int,
        open_tickets: dict[str, int],
        config_data: dict[str, Any],
    ) -> None:
        member = guild.get_member(user_id)
        try:
            await channel.send(embed=warning_embed("Ticket Auto-Closed", "This ticket was closed after 72 hours of inactivity."))
            overwrites = channel.overwrites_for(guild.default_role)
            overwrites.send_messages = False
            await channel.set_permissions(guild.default_role, overwrite=overwrites)
            if not channel.name.startswith("closed-"):
                await channel.edit(name=f"closed-{channel.name[:80]}", reason="Ticket auto-closed for inactivity")
        except discord.HTTPException as exc:
            log.warning("Could not archive stale ticket %s: %s", channel.id, exc)

        if member:
            try:
                await member.send(
                    embed=info_embed(
                        "Ticket Auto-Closed",
                        f"Your ticket in **{guild.name}** was closed due to inactivity.",
                    )
                )
            except discord.HTTPException:
                pass

        open_tickets.pop(str(user_id), None)
        claimed_tickets: dict[str, int] = config_data.get("claimed_tickets", {})
        claimed_tickets.pop(str(channel.id), None)
        config_data["claimed_tickets"] = claimed_tickets
        if hasattr(self.bot, "view_registry"):
            await self.bot.view_registry.unregister(f"ticket_control:{guild.id}:{channel.id}")  # type: ignore[attr-defined]

    async def _run_health_report(self) -> str:
        memory_text = "unavailable"
        if psutil is not None:
            process = psutil.Process()
            memory_text = f"{process.memory_info().rss / 1024 / 1024:.1f} MiB"
        uptime = _utc_now() - getattr(self.bot, "start_time", _utc_now())
        db_path = Path(config.DATABASE_FILE)
        db_size = db_path.stat().st_size if db_path.exists() else 0
        failed_cogs = getattr(self.bot, "failed_cogs", {})

        embed = info_embed(
            "Bot Health Report",
            f"Uptime: **{str(uptime).split('.')[0]}**\n"
            f"Guilds: **{len(self.bot.guilds)}**\n"
            f"Latency: **{self.bot.latency * 1000:.0f}ms**\n"
            f"Open tickets: **{await self._open_ticket_count()}**\n"
            f"DB size: **{db_size / 1024:.1f} KiB**\n"
            f"Memory: **{memory_text}**\n"
            f"Failed cogs: **{len(failed_cogs)}**",
        )
        if failed_cogs:
            failed_text = "\n".join(f"`{name}`: {reason}" for name, reason in failed_cogs.items())
            embed.add_field(name="Failed Cogs", value=failed_text[:1000], inline=False)
        await self._dm_owner(embed)
        return "health_report complete"

    async def _open_ticket_count(self) -> int:
        ticket_cog = self.bot.get_cog("TicketSystem")
        if ticket_cog is None or not hasattr(ticket_cog, "config_manager"):
            return 0
        total = 0
        for guild in self.bot.guilds:
            try:
                config_data = await ticket_cog.config_manager.get_guild(guild.id)  # type: ignore[attr-defined]
                total += len(config_data.get("open_tickets", {}))
            except Exception:
                continue
        return total

    async def _run_analytics_aggregation(self) -> str:
        path = Path(config.ANALYTICS_FILE)
        if not path.exists():
            return "analytics_aggregation skipped; no analytics file"

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read analytics file: %s", exc)
            return "analytics_aggregation failed; invalid analytics file"

        today = _date_key()
        conn = await self.db.connect()
        for guild_id, guild_data in data.items():
            await conn.execute(
                """
                INSERT INTO daily_stats (guild_id, date, data, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id, date) DO UPDATE SET
                    data = excluded.data,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(guild_id), today, json.dumps(guild_data)),
            )
            if isinstance(guild_data, dict):
                for section in ("messages", "joins", "leaves"):
                    if isinstance(guild_data.get(section), dict):
                        guild_data[section].pop(today, None)
                guild_data["commands"] = {}
        await conn.commit()

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write analytics file after aggregation: %s", exc)

        return f"analytics_aggregation complete; guilds={len(data)}"

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
    async def daily_reset(self) -> None:
        try:
            log.info(await self._run_daily_reset())
        except Exception as exc:
            log.exception("daily_reset failed: %s", exc)

    @tasks.loop(time=time(hour=9, minute=0, tzinfo=timezone.utc))
    async def weekly_leaderboard(self) -> None:
        if _utc_now().weekday() != 0:
            return
        try:
            log.info(await self._run_weekly_leaderboard())
        except Exception as exc:
            log.exception("weekly_leaderboard failed: %s", exc)

    @tasks.loop(hours=1)
    async def stale_ticket_scan(self) -> None:
        try:
            log.info(await self._run_stale_tickets())
        except Exception as exc:
            log.exception("stale_ticket_scan failed: %s", exc)

    @tasks.loop(hours=6)
    async def health_report(self) -> None:
        try:
            log.info(await self._run_health_report())
        except Exception as exc:
            log.exception("health_report failed: %s", exc)

    @tasks.loop(time=time(hour=23, minute=55, tzinfo=timezone.utc))
    async def analytics_aggregation(self) -> None:
        try:
            log.info(await self._run_analytics_aggregation())
        except Exception as exc:
            log.exception("analytics_aggregation failed: %s", exc)

    @daily_reset.before_loop
    @weekly_leaderboard.before_loop
    @stale_ticket_scan.before_loop
    @health_report.before_loop
    @analytics_aggregation.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="run-task", description="Owner only: manually run a scheduler task.")
    @app_commands.describe(task_name="Task to run")
    @app_commands.choices(
        task_name=[
            app_commands.Choice(name="Daily Reset", value="daily_reset"),
            app_commands.Choice(name="Weekly Leaderboard", value="weekly_leaderboard"),
            app_commands.Choice(name="Stale Tickets", value="stale_tickets"),
            app_commands.Choice(name="Health Report", value="health_report"),
            app_commands.Choice(name="Analytics Aggregation", value="analytics_aggregation"),
        ]
    )
    async def run_task(self, interaction: discord.Interaction, task_name: app_commands.Choice[str]) -> None:
        if not await self._owner_only(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        runners = {
            "daily_reset": self._run_daily_reset,
            "weekly_leaderboard": self._run_weekly_leaderboard,
            "stale_tickets": self._run_stale_tickets,
            "health_report": self._run_health_report,
            "analytics_aggregation": self._run_analytics_aggregation,
        }
        runner = runners[task_name.value]
        try:
            result = await runner()
        except Exception as exc:
            log.exception("Manual scheduler task %s failed: %s", task_name.value, exc)
            return await interaction.followup.send(
                embed=error_embed("Task Failed", f"`{task_name.value}` failed: `{exc}`"),
                ephemeral=True,
            )
        await interaction.followup.send(embed=success_embed("Task Complete", result), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
