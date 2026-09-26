# ===== ticket_system.py =====
# Production-ready Discord ticket system cog with persistent views,
# config persistence, blacklist, auto-delete, staff notifications,
# and zero 10062 Unknown Interaction errors via Interaction Safety Layer.

from __future__ import annotations

import asyncio
import io
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import discord
import motor.motor_asyncio
from discord import app_commands
from discord.ext import commands

import config
from core.errors import PermissionError, ResourceNotFoundError
from core.interaction import safe_defer, safe_edit, safe_followup, safe_modal, safe_send
from engines.guild.channel_engine import ChannelEngine
from engines.guild.permission_engine import PermissionPreset, permission_engine
from engines.recovery.recovery_engine import recovery_engine

# ── Constants ─────────────────────────────────────────────────────────────────
EMBED_COLOR: int = 0x5865F2
TICKET_COOLDOWN_SECONDS: int = 300  # 5 minutes
AUTO_DELETE_DELAY: int = 10  # seconds before ticket channel is deleted after close

log = logging.getLogger("cogs.ticket_system")


# ── Config Manager (MongoDB via motor with safe fallback) ─────────────────────
class ConfigManager:
    """Handles all config persistence for the ticket system using MongoDB Atlas."""

    def __init__(self) -> None:
        self.uri = config.MONGO_URI
        self.client: motor.motor_asyncio.AsyncIOMotorClient | None = None
        self.db: Any = None
        self.col: Any = None
        self._memory_cache: dict[str, dict] = {}
        self._cache: dict[str, dict] = self._memory_cache

        if self.uri:
            try:
                self.client = motor.motor_asyncio.AsyncIOMotorClient(
                    self.uri, serverSelectionTimeoutMS=2000
                )
                self.db = self.client["ticket_bot"]
                self.col = self.db["guild_configs"]
                log.info("MongoDB client connected for ticket system.")
            except Exception as exc:
                log.warning("Could not initialise MongoDB client: %s. Using in-memory store.", exc)
                self.col = None
        else:
            log.warning("MONGO_URI not configured. Ticket system will use ephemeral memory storage.")

    async def get_guild(self, guild_id: int) -> dict:
        if self.col is not None:
            try:
                doc = await asyncio.wait_for(
                    self.col.find_one({"_id": str(guild_id)}),
                    timeout=2.0,
                )
                if doc:
                    self._memory_cache[str(guild_id)] = dict(doc)
                    return doc
            except Exception as exc:
                log.warning("Failed to fetch guild config from MongoDB: %s. Using cache.", exc)
        return self._memory_cache.get(str(guild_id), {})

    async def save_guild(self, guild_id: int, data: dict) -> None:
        cleaned = dict(data)
        cleaned.pop("_id", None)
        self._memory_cache[str(guild_id)] = cleaned
        if self.col is not None:
            try:
                await asyncio.wait_for(
                    self.col.update_one(
                        {"_id": str(guild_id)},
                        {"$set": cleaned},
                        upsert=True,
                    ),
                    timeout=2.0,
                )
            except Exception as exc:
                log.warning("Failed to save guild config to MongoDB: %s", exc)
        return True

    async def get_key(self, guild_id: int, key: str, default=None):
        doc = await self.get_guild(guild_id)
        return doc.get(key, default)

    async def set_key(self, guild_id: int, key: str, value) -> None:
        gk = str(guild_id)
        if gk not in self._memory_cache:
            self._memory_cache[gk] = {}
        self._memory_cache[gk][key] = value
        if self.col is not None:
            try:
                await asyncio.wait_for(
                    self.col.update_one(
                        {"_id": str(guild_id)},
                        {"$set": {key: value}},
                        upsert=True,
                    ),
                    timeout=2.0,
                )
            except Exception as exc:
                log.warning("Failed to update key '%s' in MongoDB: %s", key, exc)

    async def delete_key(self, guild_id: int, key: str) -> None:
        gk = str(guild_id)
        if gk in self._memory_cache:
            self._memory_cache[gk].pop(key, None)
        if self.col is not None:
            try:
                await asyncio.wait_for(
                    self.col.update_one(
                        {"_id": str(guild_id)},
                        {"$unset": {key: ""}},
                        upsert=False,
                    ),
                    timeout=2.0,
                )
            except Exception as exc:
                log.warning("Failed to delete key '%s' from MongoDB: %s", key, exc)


# ── Auto-Delete Manager ──────────────────────────────────────────────────────
class AutoDeleteManager:
    """Manages scheduled auto-deletion tasks for closed ticket channels."""

    def __init__(self) -> None:
        self.pending_deletes: dict[int, asyncio.Task] = {}

    async def schedule_delete(
        self,
        channel: discord.TextChannel,
        delay: int,
        log_channel: Optional[discord.TextChannel],
        transcript_bytes: bytes,
        ticket_name: str,
    ) -> None:
        try:
            await channel.send(
                f"⏳ This ticket channel will be automatically deleted in **{delay} seconds**."
            )
            await asyncio.sleep(delay)
            await channel.delete(reason="Ticket closed — auto-deleted by ticket system.")
            log.info("Auto-deleted ticket channel: %s", ticket_name)
            if channel.id in self.pending_deletes:
                del self.pending_deletes[channel.id]
        except discord.NotFound:
            log.info("Channel %s was already deleted before auto-delete ran.", ticket_name)
        except discord.Forbidden:
            log.error("No permission to delete channel %s.", ticket_name)
        except asyncio.CancelledError:
            log.info("Auto-delete for %s was cancelled.", ticket_name)
            try:
                await channel.send("🚫 Auto-delete has been cancelled by a moderator.")
            except (discord.NotFound, discord.Forbidden):
                pass


# ── Close Ticket Modal ───────────────────────────────────────────────────────
class CloseTicketModal(discord.ui.Modal, title="Close Ticket"):
    """Modal that asks for a reason before closing a ticket."""

    reason_input = discord.ui.TextInput(
        label="Reason for closing",
        placeholder="Describe why this ticket is being closed...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, cog: "TicketSystem") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        assert isinstance(interaction.channel, discord.TextChannel)
        channel = interaction.channel
        reason = self.reason_input.value or "No reason provided."

        # Acknowledge immediately to avoid 10062
        await safe_defer(interaction, ephemeral=True)

        config_data = await self.cog.config_manager.get_guild(interaction.guild.id)
        if not config_data:
            await safe_followup(interaction, "No ticket config found for this server.", ephemeral=True)
            return

        # Find the original opener
        open_tickets: dict = config_data.get("open_tickets", {})
        opener_id: Optional[int] = None
        for uid_str, cid in open_tickets.items():
            if cid == channel.id:
                opener_id = int(uid_str)
                break

        # Determine ticket counter from channel name
        ticket_counter_str = channel.name.split("-")[1] if "-" in channel.name else "????"

        # Step 1 — Send closing embed in channel
        close_embed = discord.Embed(
            title="🔒 Ticket Closed",
            color=0xFF4444,
            timestamp=discord.utils.utcnow(),
        )
        close_embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
        close_embed.add_field(name="Reason", value=reason, inline=False)
        close_embed.add_field(
            name="Closed at",
            value=discord.utils.format_dt(discord.utils.utcnow(), style="F"),
            inline=True,
        )
        close_embed.set_footer(
            text=f"This channel will be deleted in {AUTO_DELETE_DELAY} seconds."
        )
        await channel.send(embed=close_embed)

        # Step 2 — Generate transcript
        messages = [msg async for msg in channel.history(limit=200, oldest_first=True)]
        transcript_lines: list[str] = []
        for msg in messages:
            transcript_lines.append(f"[{msg.created_at}] {msg.author}: {msg.content}")
        transcript_text = "\n".join(transcript_lines)
        transcript_bytes = transcript_text.encode("utf-8")

        # Step 3 — Post to log channel
        log_channel_id = config_data.get("log_channel_id")
        log_channel: Optional[discord.TextChannel] = None
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)  # type: ignore[assignment]

        if log_channel:
            opener_mention = f"<@{opener_id}>" if opener_id else "Unknown"
            log_embed = discord.Embed(
                title=f"📁 Ticket Closed — #{ticket_counter_str}",
                color=0xFF4444,
                timestamp=discord.utils.utcnow(),
            )
            log_embed.add_field(name="Ticket", value=channel.name, inline=True)
            log_embed.add_field(name="Opened by", value=opener_mention, inline=True)
            log_embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.add_field(
                name="Closed at",
                value=discord.utils.format_dt(discord.utils.utcnow(), style="F"),
                inline=True,
            )
            transcript_file = discord.File(
                io.BytesIO(transcript_bytes), filename=f"{channel.name}-transcript.txt"
            )
            try:
                await log_channel.send(embed=log_embed, file=transcript_file)
            except (discord.Forbidden, discord.HTTPException) as e:
                log.error("Failed to send transcript to log channel: %s", e)

        # Step 4 — Lock out the opener
        if opener_id:
            opener_member = interaction.guild.get_member(opener_id)
            if opener_member:
                try:
                    overwrites = channel.overwrites_for(opener_member)
                    overwrites.send_messages = False
                    overwrites.view_channel = True
                    await channel.set_permissions(opener_member, overwrite=overwrites)
                except (discord.Forbidden, discord.HTTPException) as e:
                    log.error("Failed to lock permissions for opener: %s", e)

        # Step 5 — Remove from config
        if opener_id and str(opener_id) in open_tickets:
            del open_tickets[str(opener_id)]
        claimed_tickets: dict = config_data.get("claimed_tickets", {})
        if str(channel.id) in claimed_tickets:
            del claimed_tickets[str(channel.id)]
        config_data["open_tickets"] = open_tickets
        config_data["claimed_tickets"] = claimed_tickets
        await self.cog.config_manager.save_guild(interaction.guild.id, config_data)

        # Step 6 — Schedule auto-delete
        delay = config_data.get("auto_delete_delay", AUTO_DELETE_DELAY)
        task = asyncio.create_task(
            self.cog.auto_delete_manager.schedule_delete(
                channel, delay, log_channel, transcript_bytes, channel.name
            )
        )
        self.cog.auto_delete_manager.pending_deletes[channel.id] = task

        await safe_followup(interaction, "Ticket has been closed successfully.", ephemeral=True)


# ── Ticket Control View (Claim / Close) ──────────────────────────────────────
class TicketControlView(discord.ui.View):
    """Persistent view inside each ticket channel with Claim and Close buttons."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ Claim Ticket",
        style=discord.ButtonStyle.success,
        custom_id="ticket_claim",
    )
    async def claim_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        assert interaction.guild is not None
        assert isinstance(interaction.channel, discord.TextChannel)

        # Immediate acknowledgement to guarantee 10062 immunity
        await safe_defer(interaction, ephemeral=True)

        cog: Optional[TicketSystem] = interaction.client.get_cog("TicketSystem")  # type: ignore[assignment]
        if cog is None:
            await safe_followup(interaction, "Ticket system is not loaded.", ephemeral=True)
            return

        config_data = await cog.config_manager.get_guild(interaction.guild.id)
        if not config_data:
            await safe_followup(interaction, "No ticket config found.", ephemeral=True)
            return

        # Permission check — must have support_role or mod_role
        support_role_id = config_data.get("support_role_id")
        mod_role_id = config_data.get("mod_role_id")
        member = interaction.user
        assert isinstance(member, discord.Member)

        has_support = any(r.id == support_role_id for r in member.roles)
        has_mod = any(r.id == mod_role_id for r in member.roles)

        if not has_support and not has_mod and not member.guild_permissions.manage_channels:
            await safe_followup(interaction, "Only support staff can claim tickets.", ephemeral=True)
            return

        # Already claimed check
        claimed_tickets: dict = config_data.get("claimed_tickets", {})
        channel_id_str = str(interaction.channel.id)
        if channel_id_str in claimed_tickets:
            claimer_id = claimed_tickets[channel_id_str]
            await safe_followup(interaction, f"This ticket was already claimed by <@{claimer_id}>.", ephemeral=True)
            return

        # Claim it
        claimed_tickets[channel_id_str] = interaction.user.id
        config_data["claimed_tickets"] = claimed_tickets
        await cog.config_manager.save_guild(interaction.guild.id, config_data)

        claim_embed = discord.Embed(
            title="✅ Ticket Claimed",
            color=0x00FF7F,
            timestamp=discord.utils.utcnow(),
        )
        claim_embed.add_field(name="Claimed by", value=interaction.user.mention, inline=True)
        claim_embed.add_field(
            name="Claimed at",
            value=discord.utils.format_dt(discord.utils.utcnow(), style="F"),
            inline=True,
        )
        await interaction.channel.send(embed=claim_embed)

        # Attempt to edit original control embed
        try:
            control_msg_id = config_data.get("control_messages", {}).get(str(interaction.channel.id))
            if control_msg_id:
                control_msg = await interaction.channel.fetch_message(control_msg_id)
                if control_msg.embeds:
                    embed = control_msg.embeds[0].copy()
                    embed.add_field(name="Claimed by", value=interaction.user.mention, inline=True)
                    await control_msg.edit(embed=embed)
        except Exception as e:
            log.warning("Could not edit control message to add claim info: %s", e)

        await safe_followup(interaction, "You have claimed this ticket.", ephemeral=True)
        log.info("Ticket %s claimed by %s", interaction.channel.name, interaction.user)

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_close",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        assert interaction.guild is not None
        assert isinstance(interaction.channel, discord.TextChannel)

        cog: Optional[TicketSystem] = interaction.client.get_cog("TicketSystem")  # type: ignore[assignment]
        if cog is None:
            await safe_send(interaction, "Ticket system is not loaded.", ephemeral=True)
            return

        # Modals CANNOT be deferred before sending, send modal immediately
        modal = CloseTicketModal(cog)
        sent = await safe_modal(interaction, modal)
        if not sent:
            log.warning("Failed to open close ticket modal.")


# ── Ticket Panel View (Tech / Server / Mod) ──────────────────────────────────
class TicketPanelView(discord.ui.View):
    """Persistent panel view with three ticket type buttons."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔧 Tech Support",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_panel_tech",
    )
    async def tech_support(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog: Optional[TicketSystem] = interaction.client.get_cog("TicketSystem")  # type: ignore[assignment]
        if cog:
            await cog.create_ticket(interaction, "Tech Support")

    @discord.ui.button(
        label="🛡️ Server Support",
        style=discord.ButtonStyle.success,
        custom_id="ticket_panel_server",
    )
    async def server_support(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog: Optional[TicketSystem] = interaction.client.get_cog("TicketSystem")  # type: ignore[assignment]
        if cog:
            await cog.create_ticket(interaction, "Server Support")

    @discord.ui.button(
        label="⚔️ Mod Support",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_panel_mod",
    )
    async def mod_support(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog: Optional[TicketSystem] = interaction.client.get_cog("TicketSystem")  # type: ignore[assignment]
        if cog:
            await cog.create_ticket(interaction, "Mod Support")


# ── Blacklist Command Group ────────────────────────────────────────────────────
class TicketBlacklist(app_commands.Group):
    """Manage the ticket blacklist."""

    def __init__(self, cog: "TicketSystem") -> None:
        super().__init__(name="ticket_blacklist", description="Manage ticket blacklist")
        self.cog = cog

    @app_commands.command(name="add", description="Blacklist a user from opening tickets.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(user="The user to blacklist")
    async def blacklist_add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        assert interaction.guild is not None
        await safe_defer(interaction, ephemeral=True)
        config_data = await self.cog.config_manager.get_guild(interaction.guild.id)
        if not config_data:
            await safe_followup(interaction, "No ticket config found. Run /setup_tickets first.", ephemeral=True)
            return

        blacklist: list = config_data.get("blacklisted_users", [])
        if user.id in blacklist:
            await safe_followup(interaction, "User is already blacklisted.", ephemeral=True)
            return

        blacklist.append(user.id)
        config_data["blacklisted_users"] = blacklist
        await self.cog.config_manager.save_guild(interaction.guild.id, config_data)

        embed = discord.Embed(title="🚫 User Blacklisted", color=0xFF4444)
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Added by", value=interaction.user.mention, inline=True)
        await safe_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="remove", description="Remove a user from the ticket blacklist.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(user="The user to remove from the blacklist")
    async def blacklist_remove(self, interaction: discord.Interaction, user: discord.Member) -> None:
        assert interaction.guild is not None
        await safe_defer(interaction, ephemeral=True)
        config_data = await self.cog.config_manager.get_guild(interaction.guild.id)
        if not config_data:
            await safe_followup(interaction, "No ticket config found. Run /setup_tickets first.", ephemeral=True)
            return

        blacklist: list = config_data.get("blacklisted_users", [])
        if user.id not in blacklist:
            await safe_followup(interaction, "User is not blacklisted.", ephemeral=True)
            return

        blacklist.remove(user.id)
        config_data["blacklisted_users"] = blacklist
        await self.cog.config_manager.save_guild(interaction.guild.id, config_data)

        embed = discord.Embed(title="✅ User Removed from Blacklist", color=0x00FF7F)
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Removed by", value=interaction.user.mention, inline=True)
        await safe_followup(interaction, embed=embed, ephemeral=True)

    @app_commands.command(name="list", description="View all blacklisted users.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blacklist_list(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await safe_defer(interaction, ephemeral=True)
        config_data = await self.cog.config_manager.get_guild(interaction.guild.id)
        if not config_data:
            await safe_followup(interaction, "No ticket config found. Run /setup_tickets first.", ephemeral=True)
            return

        blacklist: list = config_data.get("blacklisted_users", [])
        if not blacklist:
            await safe_followup(interaction, "No users are blacklisted.", ephemeral=True)
            return

        mentions = "\n".join(f"<@{uid}>" for uid in blacklist)
        embed = discord.Embed(
            title="🚫 Blacklisted Users",
            description=mentions,
            color=0xFF4444,
        )
        await safe_followup(interaction, embed=embed, ephemeral=True)


# ── Main Cog ─────────────────────────────────────────────────────────────────
class TicketSystem(commands.Cog):
    """Full-featured ticket system with persistent views, blacklist, auto-delete, and interaction safety."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config_manager = ConfigManager()
        self.auto_delete_manager = AutoDeleteManager()
        self.ticket_cooldowns: dict[int, datetime] = {}
        self.channel_engine = ChannelEngine()

        # Register blacklist command group
        self.blacklist_group = TicketBlacklist(self)
        self.bot.tree.add_command(self.blacklist_group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("ticket_blacklist", type=discord.AppCommandType.chat_input)
        for task in self.auto_delete_manager.pending_deletes.values():
            task.cancel()

    async def cog_load(self) -> None:
        # Register persistent views
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketControlView())

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _sanitize_username(name: str) -> str:
        sanitized = name.lower().replace(" ", "-")
        return "".join(c for c in sanitized if c.isalnum() or c == "-")

    def _check_cooldown(self, user_id: int) -> Optional[int]:
        last = self.ticket_cooldowns.get(user_id)
        if last is None:
            return None
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        remaining = TICKET_COOLDOWN_SECONDS - elapsed
        if remaining > 0:
            return int(remaining)
        return None

    # ── /setup_tickets ────────────────────────────────────────────────────────
    @app_commands.command(
        name="setup_tickets",
        description="Set up the ticket system panel with roles, channels, and optional image.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        title="Embed title for the ticket panel",
        description="Embed description text",
        support_role="Role pinged for tech/server tickets",
        mod_role="Role pinged for mod tickets",
        log_channel="Channel where ticket logs are posted",
        ticket_category="Category where ticket channels are created",
        ticket_image="Custom image used as the ticket panel banner",
    )
    async def setup_tickets(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        support_role: discord.Role,
        mod_role: discord.Role,
        log_channel: discord.TextChannel,
        ticket_category: discord.CategoryChannel,
        ticket_image: Optional[discord.Attachment] = None,
    ) -> None:
        assert interaction.guild is not None

        # ACKNOWLEDGE FIRST to eliminate 10062 risk
        await safe_defer(interaction, ephemeral=True)

        # Validate bot permissions
        bot_member = interaction.guild.me
        if not bot_member:
            await safe_followup(interaction, "Could not determine bot permissions.", ephemeral=True)
            return

        required_perms = {
            "manage_channels": bot_member.guild_permissions.manage_channels,
            "send_messages": bot_member.guild_permissions.send_messages,
            "attach_files": bot_member.guild_permissions.attach_files,
        }
        missing = [name for name, has in required_perms.items() if not has]
        if missing:
            await safe_followup(
                interaction,
                f"❌ Missing required bot permissions: {', '.join(missing)}. Please grant them in Server Settings -> Roles.",
                ephemeral=True,
            )
            return

        # Validate image if provided
        ticket_image_url: Optional[str] = None
        if ticket_image is not None:
            if not ticket_image.content_type or not ticket_image.content_type.startswith("image/"):
                await safe_followup(interaction, "The uploaded file is not a valid image.", ephemeral=True)
                return
            ticket_image_url = ticket_image.url

        # Load existing config
        config_data = await self.config_manager.get_guild(interaction.guild.id)

        # Build the panel embed
        panel_embed = discord.Embed(
            title=title,
            description=description,
            color=EMBED_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        panel_embed.set_footer(text="Click a button below to open a support ticket.")
        if ticket_image_url:
            panel_embed.set_image(url=ticket_image_url)

        from core.discord_api.guard import api_guard
        allowed, api_state, _ = api_guard.can_execute()
        if not allowed:
            await safe_followup(
                interaction,
                f"Discord API is currently {api_state.value}. Cannot set up tickets right now.",
                ephemeral=True,
            )
            return

        # Send panel
        panel_view = TicketPanelView()
        panel_msg = await interaction.channel.send(embed=panel_embed, view=panel_view)  # type: ignore[union-attr]

        # Register the view for persistence
        self.bot.add_view(panel_view)

        # Save config
        config_data.update(
            {
                "support_role_id": support_role.id,
                "mod_role_id": mod_role.id,
                "log_channel_id": log_channel.id,
                "ticket_category_id": ticket_category.id,
                "panel_message_id": panel_msg.id,
                "panel_channel_id": interaction.channel.id,  # type: ignore[union-attr]
                "ticket_image_url": ticket_image_url,
            }
        )
        config_data.setdefault("ticket_counter", 0)
        config_data.setdefault("open_tickets", {})
        config_data.setdefault("claimed_tickets", {})
        config_data.setdefault("blacklisted_users", [])
        config_data.setdefault("auto_delete_delay", AUTO_DELETE_DELAY)
        config_data.setdefault("control_messages", {})

        await self.config_manager.save_guild(interaction.guild.id, config_data)
        await safe_followup(interaction, "Ticket panel created successfully! ✅", ephemeral=True)
        log.info("Ticket panel set up in guild %s by %s", interaction.guild.id, interaction.user)

    # ── Ticket Creation (called by panel buttons) ───────────────────────────
    async def create_ticket(
        self, interaction: discord.Interaction, ticket_type: str
    ) -> None:
        """Create ticket with IMMEDIATE ACKNOWLEDGEMENT to eliminate 10062 Unknown Interaction."""
        assert interaction.guild is not None

        # 1. IMMEDIATE ACKNOWLEDGEMENT FIRST — BEFORE ANY ASYNC CALLS OR DB ACCESS!
        defer_res = await safe_defer(interaction, ephemeral=True)
        if not defer_res:
            log.warning(
                "[TICKET] action=create result=ABORTED reason=%s",
                getattr(defer_res, "reason", "DEFER_FAILED"),
            )
            return

        # 2. LOAD CONFIG
        config_data = await self.config_manager.get_guild(interaction.guild.id)
        if not config_data:
            await safe_followup(
                interaction,
                "This server has no ticket setup. Ask an admin to run `/setup_tickets`.",
                ephemeral=True,
            )
            return

        # 3. BLACKLIST CHECK
        blacklist: list = config_data.get("blacklisted_users", [])
        if interaction.user.id in blacklist:
            await safe_followup(
                interaction,
                "You are not permitted to open tickets in this server.",
                ephemeral=True,
            )
            return

        # 4. EXISTING OPEN TICKET CHECK
        open_tickets: dict = config_data.get("open_tickets", {})
        user_id_str = str(interaction.user.id)
        if user_id_str in open_tickets:
            existing_channel_id = open_tickets[user_id_str]
            existing_channel = interaction.guild.get_channel(existing_channel_id)
            if existing_channel:
                await safe_followup(
                    interaction,
                    f"You already have an open ticket: {existing_channel.mention}. Please resolve it before opening a new one.",
                    ephemeral=True,
                )
                return
            else:
                # Stale reference cleanup
                del open_tickets[user_id_str]
                config_data["open_tickets"] = open_tickets
                await self.config_manager.save_guild(interaction.guild.id, config_data)

        # 5. COOLDOWN CHECK
        remaining = self._check_cooldown(interaction.user.id)
        if remaining is not None:
            await safe_followup(
                interaction,
                f"Please wait **{remaining} seconds** before opening another ticket.",
                ephemeral=True,
            )
            return

        # 6. RESOLVE CATEGORY & ROLES
        category_id = config_data.get("ticket_category_id", 0)
        category = interaction.guild.get_channel(category_id)
        if not category or (not isinstance(category, discord.CategoryChannel) and getattr(category, "type", None) != discord.ChannelType.category):
            await safe_followup(
                interaction,
                "❌ Ticket category not found. Please ask an admin to reconfigure tickets with `/setup_tickets`.",
                ephemeral=True,
            )
            return

        support_role = interaction.guild.get_role(config_data.get("support_role_id", 0))
        mod_role = interaction.guild.get_role(config_data.get("mod_role_id", 0))

        counter = config_data.get("ticket_counter", 0) + 1
        sanitized_name = self._sanitize_username(interaction.user.name)
        ticket_id = f"ticket-{counter:04d}-{sanitized_name}"

        # 7. BUILD PERMISSION OVERWRITES VIA PERMISSION ENGINE
        overwrites = permission_engine.build_overwrites_for_preset(
            guild=interaction.guild,
            preset=PermissionPreset.TICKET,
            ticket_opener=interaction.user,  # type: ignore[arg-type]
        )
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
            )
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
            )

        # 8. CREATE CHANNEL VIA CHANNEL ENGINE & RECOVERY
        try:
            channel_params = {
                "name": ticket_id,
                "type": "text",
                "category": category,
                "topic": f"Ticket opened by {interaction.user} ({ticket_type})",
            }
            # Create text channel via ChannelEngine with calculated overwrites
            ticket_channel = await ChannelEngine.create_text_channel(
                guild=interaction.guild,
                name=ticket_id,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket opened by {interaction.user} ({ticket_type})",
                reason=f"Ticket opened by {interaction.user} ({ticket_type})",
            )
            if not ticket_channel:
                await safe_followup(
                    interaction,
                    "❌ Failed to create ticket channel. Discord API may be restricted.",
                    ephemeral=True,
                )
                return
        except discord.Forbidden:
            log.error("Bot lacks permission to create ticket channel in guild %s", interaction.guild.id)
            await safe_followup(
                interaction,
                "❌ Failed to create ticket channel: DAMU lacks `Manage Channels` permission.",
                ephemeral=True,
            )
            return
        except Exception as e:
            log.error("Failed to create ticket channel for %s: %s", interaction.user, e)
            await safe_followup(
                interaction,
                f"❌ Failed to create ticket channel: {e}",
                ephemeral=True,
            )
            return

        # 9. SEND CONTROL PANEL & PERSIST (TRANSACTIONAL WITH ROLLBACK)
        try:
            ticket_embed = discord.Embed(
                title=f"Ticket #{counter:04d}",
                color=EMBED_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            ticket_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            ticket_image_url = config_data.get("ticket_image_url")
            if ticket_image_url:
                ticket_embed.set_image(url=ticket_image_url)
            ticket_embed.add_field(name="Opened by", value=interaction.user.mention, inline=True)
            ticket_embed.add_field(name="Ticket Type", value=ticket_type, inline=True)
            ticket_embed.add_field(
                name="Opened at",
                value=discord.utils.format_dt(discord.utils.utcnow(), style="F"),
                inline=True,
            )
            ticket_embed.set_footer(text="Use the buttons below to manage this ticket.")

            mention_parts: list[str] = []
            if support_role and getattr(support_role, "mention", None):
                mention_parts.append(str(support_role.mention))
            if mod_role and getattr(mod_role, "mention", None):
                mention_parts.append(str(mod_role.mention))
            mention_text = " ".join(mention_parts) + " — a new ticket has been opened." if mention_parts else "A new ticket has been opened."

            control_view = TicketControlView()
            control_msg = await ticket_channel.send(
                content=mention_text,
                embed=ticket_embed,
                view=control_view,
            )

            # 10. PERSIST STATE
            control_messages: dict = config_data.get("control_messages", {})
            control_messages[str(ticket_channel.id)] = control_msg.id
            config_data["control_messages"] = control_messages
            open_tickets[user_id_str] = ticket_channel.id
            config_data["open_tickets"] = open_tickets
            config_data["ticket_counter"] = counter
            await self.config_manager.save_guild(interaction.guild.id, config_data)

            self.ticket_cooldowns[interaction.user.id] = datetime.now(timezone.utc)
            log.info("Ticket %s created by %s in guild %s", ticket_id, interaction.user, interaction.guild.id)

            # 11. RESPOND TO USER
            await safe_followup(
                interaction,
                f"Your ticket has been created: {ticket_channel.mention}",
                ephemeral=True,
            )

            # 12. NOTIFY STAFF (Asynchronous, non-blocking)
            asyncio.create_task(
                self.notify_staff(
                    interaction.guild, ticket_channel, interaction.user, ticket_type, config_data
                )
            )
        except Exception as exc:
            # ── ROLLBACK ON FAILURE ───────────────────────────────────────────
            log.exception("[TICKET] Transaction failed during setup. Rolling back created channel %s: %s", ticket_id, exc)
            await ChannelEngine.delete_channel_safe(
                ticket_channel,
                reason="Ticket transaction rollback due to initialization error",
            )
            # Revert in-memory state
            open_tickets.pop(user_id_str, None)
            config_data["open_tickets"] = open_tickets
            await self.config_manager.save_guild(interaction.guild.id, config_data)

            await safe_send(
                interaction,
                content="An error occurred while initializing your ticket. Creation was safely rolled back.",
                ephemeral=True,
            )

    # ── Staff Notification ─────────────────────────────────────────────────────
    async def notify_staff(
        self,
        guild: discord.Guild,
        ticket_channel: discord.TextChannel,
        opener: discord.User | discord.Member,
        ticket_type: str,
        config_data: dict,
    ) -> None:
        dm_embed = discord.Embed(
            title="📩 New Ticket Opened",
            color=0xFFA500,
            timestamp=discord.utils.utcnow(),
        )
        dm_embed.add_field(
            name="Opened by", value=f"{opener.mention} ({opener.name})", inline=True
        )
        dm_embed.add_field(name="Ticket Type", value=ticket_type, inline=True)
        jump_url = getattr(ticket_channel, "jump_url", f"https://discord.com/channels/{guild.id}/{ticket_channel.id}")
        dm_embed.add_field(name="Jump Link", value=jump_url, inline=False)

        targets: set[discord.Member] = set()
        if guild.owner:
            targets.add(guild.owner)

        mod_role_id = config_data.get("mod_role_id")
        if mod_role_id:
            mod_role = guild.get_role(mod_role_id)
            if mod_role:
                for member in mod_role.members:
                    targets.add(member)

        for target in targets:
            try:
                await target.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        log_channel_id = config_data.get("log_channel_id")
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel and isinstance(log_channel, discord.TextChannel):
                try:
                    await log_channel.send(embed=dm_embed)
                except (discord.Forbidden, discord.HTTPException) as e:
                    log.error("Failed to send to log channel: %s", e)

    # ── /cancel_delete ────────────────────────────────────────────────────────
    @app_commands.command(
        name="cancel_delete",
        description="Cancel the auto-delete timer for the current ticket channel.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cancel_delete(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        assert interaction.channel is not None
        await safe_defer(interaction, ephemeral=True)

        channel_id = interaction.channel.id
        if channel_id in self.auto_delete_manager.pending_deletes:
            task = self.auto_delete_manager.pending_deletes.pop(channel_id)
            task.cancel()
            await safe_followup(interaction, "Auto-delete cancelled for this channel.", ephemeral=False)
            log.info("Auto-delete cancelled for channel %s by %s", channel_id, interaction.user)
        else:
            await safe_followup(interaction, "No auto-delete is scheduled for this channel.", ephemeral=True)


# ── Setup Function ────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketSystem(bot))
