"""Server and global reporting commands and schedules."""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from services import report_service
from services.database import get_database
from services.embed_service import error_embed, success_embed
from utils.decorators import dev_only, guild_only

log = logging.getLogger("cogs.reports")


def _report_channel_key(guild_id: int) -> str:
    return f"server_report_channel:{guild_id}"


class ReportsCog(commands.Cog, name="Reports"):
    """Scheduled and manual reports with strict guild/global data boundaries."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = get_database()

    async def cog_load(self) -> None:
        self.weekly_server_reports.start()
        self.weekly_global_report.start()

    async def cog_unload(self) -> None:
        self.weekly_server_reports.cancel()
        self.weekly_global_report.cancel()

    async def _configured_report_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.db.get("guild_settings", _report_channel_key(guild.id), 0)
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _send_server_report(self, guild: discord.Guild) -> bool:
        embed = await report_service.build_server_report_embed(self.bot, guild)
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except discord.HTTPException:
                owner = None

        if owner is not None and owner.id == guild.owner_id:
            try:
                await owner.send(embed=embed)
                return True
            except discord.HTTPException:
                log.warning("Could not DM server report to owner %s for guild %s", guild.owner_id, guild.id)

        channel = await self._configured_report_channel(guild)
        if channel is None:
            log.warning("No report fallback channel configured for guild %s", guild.id)
            return False
        try:
            await channel.send(embed=embed)
            return True
        except discord.HTTPException as exc:
            log.warning("Could not send report fallback in guild %s: %s", guild.id, exc)
            return False

    async def _send_global_report(self) -> bool:
        owner_id = getattr(config, "BOT_OWNER_ID", 0)
        if not owner_id:
            log.error("Refusing to send global report because BOT_OWNER_ID is unset or 0.")
            return False
        owner = self.bot.get_user(owner_id)
        if owner is None:
            try:
                owner = await self.bot.fetch_user(owner_id)
            except discord.HTTPException:
                owner = None
        if owner is None or owner.id != owner_id:
            log.error("Refusing to send global report; bot owner recipient could not be verified.")
            return False

        embed = await report_service.build_global_report_embed(self.bot)
        assert owner.id == owner_id
        try:
            await owner.send(embed=embed)
            return True
        except discord.HTTPException as exc:
            log.warning("Could not DM global report to bot owner %s: %s", owner_id, exc)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await report_service.record_counter(member.guild.id, "members", "joins")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await report_service.record_counter(member.guild.id, "members", "leaves")

    @tasks.loop(time=time(hour=9, minute=30, tzinfo=timezone.utc))
    async def weekly_server_reports(self) -> None:
        await self.bot.wait_until_ready()
        if datetime.now(timezone.utc).weekday() != 0:
            return
        for guild in self.bot.guilds:
            await self._send_server_report(guild)

    @tasks.loop(time=time(hour=10, minute=0, tzinfo=timezone.utc))
    async def weekly_global_report(self) -> None:
        await self.bot.wait_until_ready()
        if datetime.now(timezone.utc).weekday() != 0:
            return
        await self._send_global_report()

    @weekly_server_reports.before_loop
    @weekly_global_report.before_loop
    async def before_report_tasks(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="server_report", description="Send this server's report to the server owner.")
    @guild_only()
    async def server_report(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=error_embed("Owner Only", "Only this server's owner can request the server report."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        sent = await self._send_server_report(interaction.guild)
        title = "Report Sent" if sent else "Report Not Sent"
        body = "The report was delivered." if sent else "DM delivery failed and no fallback channel is configured."
        await interaction.followup.send(embed=success_embed(title, body), ephemeral=True)

    @app_commands.command(name="global_report", description="Developer only: DM the global report to the bot owner.")
    @dev_only()
    async def global_report(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        sent = await self._send_global_report()
        title = "Global Report Sent" if sent else "Global Report Not Sent"
        body = "The report was delivered to the configured bot owner." if sent else "The bot owner recipient could not be verified."
        await interaction.followup.send(embed=success_embed(title, body), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReportsCog(bot))
