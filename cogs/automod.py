"""Automatic moderation for links and burst image spam."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from typing import Any

import aiofiles
import discord
from discord import app_commands
from discord.ext import commands

import config
from services.embed_service import error_embed, info_embed, success_embed, warning_embed

log = logging.getLogger("cogs.automod")

LINK_RE = re.compile(
    r"(?i)\b(?:https?://|www\.|discord\.gg/|discord\.com/invite/)[^\s<>()]+"
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff")
IMAGE_WINDOW_SECONDS = 1.0
MAX_IMAGES_PER_WINDOW = 3
REPEAT_TIMEOUT_MINUTES = 10
OFFENSE_RESET_HOURS = 24


class AutoModCog(commands.Cog, name="AutoMod"):
    """Optimized automatic moderation for common raid/spam patterns."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._image_windows: dict[tuple[int, int], deque[tuple[float, int]]] = defaultdict(deque)
        self._offenses: dict[str, Any] = {}
        self._settings: dict[str, Any] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def _load(self) -> None:
        if self._loaded:
            return
        if os.path.exists(config.AUTOMOD_FILE):
            try:
                async with aiofiles.open(config.AUTOMOD_FILE, "r", encoding="utf-8") as f:
                    raw = await f.read()
                data = json.loads(raw) if raw.strip() else {}
                if "offenses" in data or "settings" in data:
                    self._offenses = data.get("offenses", {})
                    self._settings = data.get("settings", {})
                else:
                    self._offenses = data
                    self._settings = {}
            except (OSError, json.JSONDecodeError):
                self._offenses = {}
                self._settings = {}
        self._loaded = True

    async def _save(self) -> None:
        os.makedirs(os.path.dirname(config.AUTOMOD_FILE), exist_ok=True)
        async with aiofiles.open(config.AUTOMOD_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps({"offenses": self._offenses, "settings": self._settings}, indent=2))

    @staticmethod
    def _key(guild_id: int, user_id: int) -> str:
        return f"{guild_id}:{user_id}"

    @staticmethod
    def _is_image_attachment(attachment: discord.Attachment) -> bool:
        content_type = (attachment.content_type or "").lower()
        filename = attachment.filename.lower()
        return content_type.startswith("image/") or filename.endswith(IMAGE_EXTENSIONS)

    @staticmethod
    def _is_exempt(member: discord.Member) -> bool:
        perms = member.guild_permissions
        return perms.administrator or perms.manage_guild or perms.manage_messages

    def _guild_settings(self, guild_id: int) -> dict[str, list[int]]:
        key = str(guild_id)
        settings = self._settings.setdefault(key, {})
        settings.setdefault("ignored_channel_ids", [])
        settings.setdefault("bypass_role_ids", [])
        return settings

    def _is_ignored_channel(self, guild_id: int, channel_id: int) -> bool:
        settings = self._guild_settings(guild_id)
        return channel_id in set(settings.get("ignored_channel_ids", []))

    def _has_bypass_role(self, guild_id: int, member: discord.Member) -> bool:
        settings = self._guild_settings(guild_id)
        bypass_ids = set(settings.get("bypass_role_ids", []))
        return any(role.id in bypass_ids for role in member.roles)

    def _count_recent_images(self, guild_id: int, user_id: int, image_count: int) -> int:
        now = time.monotonic()
        window = self._image_windows[(guild_id, user_id)]
        cutoff = now - IMAGE_WINDOW_SECONDS
        while window and window[0][0] < cutoff:
            window.popleft()
        if image_count:
            window.append((now, image_count))
        return sum(count for _, count in window)

    async def _record_offense(self, guild_id: int, user_id: int, reason: str) -> int:
        await self._load()
        now = datetime.datetime.now(datetime.timezone.utc)
        async with self._lock:
            key = self._key(guild_id, user_id)
            record = self._offenses.get(key, {"count": 0, "last_reason": "", "last_at": ""})
            last_at = record.get("last_at")
            if last_at:
                try:
                    last_dt = datetime.datetime.fromisoformat(last_at)
                    if now - last_dt > datetime.timedelta(hours=OFFENSE_RESET_HOURS):
                        record["count"] = 0
                except ValueError:
                    record["count"] = 0
            record["count"] = int(record.get("count", 0)) + 1
            record["last_reason"] = reason
            record["last_at"] = now.isoformat()
            self._offenses[key] = record
            await self._save()
            return int(record["count"])

    async def _dm_user_warning(self, member: discord.Member, reason: str, count: int) -> None:
        embed = warning_embed(
            "AutoMod Warning",
            (
                f"Your message in **{member.guild.name}** was removed.\n"
                f"Reason: **{reason}**\n"
                f"AutoMod offenses in the last {OFFENSE_RESET_HOURS}h: **{count}**"
            ),
        )
        try:
            await member.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _notify_owners(self, member: discord.Member, reason: str, count: int) -> None:
        owner_ids = {member.guild.owner_id, config.BOT_OWNER_ID}
        embed = warning_embed(
            "AutoMod Timeout Applied",
            (
                f"Server: **{member.guild.name}** (`{member.guild.id}`)\n"
                f"User: {member.mention} (`{member.id}`)\n"
                f"Reason: **{reason}**\n"
                f"Offense count: **{count}**\n"
                f"Action: **10 minute timeout**"
            ),
        )
        for user_id in owner_ids:
            if not user_id:
                continue
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _send_channel_notice(self, message: discord.Message, reason: str, timed_out: bool) -> None:
        if not isinstance(message.channel, discord.TextChannel):
            return
        action = "removed and timed out for 10 minutes" if timed_out else "removed and warned"
        try:
            await message.channel.send(
                embed=warning_embed(
                    "AutoMod Action",
                    f"{message.author.mention}, your message was {action}.\nReason: **{reason}**",
                ),
                delete_after=10,
            )
        except discord.HTTPException:
            pass

    async def _handle_violation(self, message: discord.Message, reason: str) -> None:
        if not message.guild or not isinstance(message.author, discord.Member):
            return

        member = message.author
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        count = await self._record_offense(message.guild.id, member.id, reason)
        await self._dm_user_warning(member, reason, count)

        timed_out = False
        if count >= 2:
            try:
                await member.timeout(
                    datetime.timedelta(minutes=REPEAT_TIMEOUT_MINUTES),
                    reason=f"AutoMod repeat offense: {reason}",
                )
                timed_out = True
                await self._notify_owners(member, reason, count)
            except discord.Forbidden:
                await self._notify_owners(member, f"{reason} (timeout failed: role/permission issue)", count)
            except discord.HTTPException:
                await self._notify_owners(member, f"{reason} (timeout failed: Discord API error)", count)

        await self._send_channel_notice(message, reason, timed_out)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not isinstance(message.author, discord.Member):
            return
        await self._load()
        if self._is_ignored_channel(message.guild.id, message.channel.id):
            return
        if message.author.bot or self._is_exempt(message.author):
            return
        if self._has_bypass_role(message.guild.id, message.author):
            return

        if LINK_RE.search(message.content or ""):
            await self._handle_violation(message, "Links are not allowed")
            return

        image_count = sum(1 for attachment in message.attachments if self._is_image_attachment(attachment))
        if image_count:
            total_images = self._count_recent_images(message.guild.id, message.author.id, image_count)
            if total_images > MAX_IMAGES_PER_WINDOW:
                await self._handle_violation(
                    message,
                    f"Image spam: more than {MAX_IMAGES_PER_WINDOW} images in {IMAGE_WINDOW_SECONDS:.0f}s",
                )

    @app_commands.command(name="automod_status", description="Show AutoMod settings and recent offense count.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def automod_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await self._load()
        prefix = f"{interaction.guild.id}:"
        total = sum(1 for key in self._offenses if key.startswith(prefix))
        settings = self._guild_settings(interaction.guild.id)
        ignored_channels = settings.get("ignored_channel_ids", [])
        bypass_roles = settings.get("bypass_role_ids", [])
        embed = info_embed(
            "AutoMod Status",
            (
                "**Enabled:** yes\n"
                "**Deletes:** links, image bursts over 3 images in 1 second\n"
                "**First offense:** delete + warn\n"
                "**Repeat offense:** 10 minute timeout + DM server owner and bot owner\n"
                f"**Tracked users in this server:** {total}\n"
                f"**Ignored channels:** {len(ignored_channels)}\n"
                f"**Bypass roles:** {len(bypass_roles)}"
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="automod_exception", description="Add, remove, or list AutoMod exception channels/roles by ID.")
    @app_commands.describe(
        action="Add, remove, or list exceptions",
        target="Whether this is a channel exception or role bypass",
        id_value="Channel ID or role ID. Not needed for list.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Add", value="add"),
            app_commands.Choice(name="Remove", value="remove"),
            app_commands.Choice(name="List", value="list"),
        ],
        target=[
            app_commands.Choice(name="Ignored Channel", value="channel"),
            app_commands.Choice(name="Bypass Role", value="role"),
        ],
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def automod_exception(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        target: app_commands.Choice[str],
        id_value: str | None = None,
    ) -> None:
        if not interaction.guild:
            return
        await self._load()
        settings = self._guild_settings(interaction.guild.id)
        key = "ignored_channel_ids" if target.value == "channel" else "bypass_role_ids"

        if action.value == "list":
            channel_lines = [
                f"- <#{channel_id}> (`{channel_id}`)" for channel_id in settings.get("ignored_channel_ids", [])
            ]
            role_lines = [
                f"- <@&{role_id}> (`{role_id}`)" for role_id in settings.get("bypass_role_ids", [])
            ]
            text = (
                "**Ignored Channels**\n"
                f"{chr(10).join(channel_lines) if channel_lines else 'None'}\n\n"
                "**Bypass Roles**\n"
                f"{chr(10).join(role_lines) if role_lines else 'None'}"
            )
            return await interaction.response.send_message(
                embed=info_embed("AutoMod Exceptions", text),
                ephemeral=True,
            )

        if not id_value or not id_value.strip().isdigit():
            return await interaction.response.send_message(
                embed=error_embed("Invalid ID", "Give a numeric channel ID or role ID."),
                ephemeral=True,
            )

        item_id = int(id_value.strip())
        values = set(settings.get(key, []))
        if action.value == "add":
            values.add(item_id)
            verb = "added to"
        else:
            values.discard(item_id)
            verb = "removed from"

        settings[key] = sorted(values)
        async with self._lock:
            await self._save()

        mention = f"<#{item_id}>" if target.value == "channel" else f"<@&{item_id}>"
        await interaction.response.send_message(
            embed=success_embed(
                "AutoMod Exception Updated",
                f"{mention} (`{item_id}`) {verb} AutoMod {'ignored channels' if target.value == 'channel' else 'bypass roles'}.",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="automod_reset", description="Reset AutoMod offenses for a member.")
    @app_commands.describe(user="Member whose AutoMod offenses should be cleared")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def automod_reset(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not interaction.guild:
            return
        await self._load()
        async with self._lock:
            self._offenses.pop(self._key(interaction.guild.id, user.id), None)
            await self._save()
        await interaction.response.send_message(
            embed=success_embed("AutoMod Reset", f"AutoMod offenses cleared for {user.mention}."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoModCog(bot))
