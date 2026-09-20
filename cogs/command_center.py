"""Interactive Administrator Command Center — /dashboard."""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands

from builder.audit import run_server_audit
from builder.interactive_builder import (
    InteractiveCategoryBuilderView,
    InteractiveChannelBuilderView,
)
from services.embed_service import info_embed, success_embed
from services.repositories import (
    AutoModRepository,
    BuildRepository,
    GuildRepository,
    SnapshotRepository,
    TicketRepository,
)

log = logging.getLogger("cogs.command_center")

SECTIONS = [
    ("🏗️ Server Builder", "builder", "Templates, custom JSON, AI generation, and previews"),
    ("🔐 Permissions", "permissions", "Three-state editor, role matrix, and presets"),
    ("🎭 Roles", "roles", "Role creator, presets, and hierarchy validation"),
    ("📁 Categories", "categories", "Interactive category builder and cloning"),
    ("💬 Channels", "channels", "Text, Voice, Forum, Stage, Announcement builder"),
    ("🛡️ AutoMod", "automod", "Filters for bad words, invites, links, and spam"),
    ("✅ Verification", "verification", "Gatekeeper verification setup and roles"),
    ("🎫 Tickets", "tickets", "Support ticket system and transcripts"),
    ("👋 Welcome", "welcome", "Member greeting and farewell messages"),
    ("🔨 Moderation", "moderation", "Warns, mutes, kicks, bans, and audit history"),
    ("📊 Analytics", "analytics", "Daily message, voice, and member stats"),
    ("🤖 AI Assistant", "ai", "Natural-language server configuration and chat"),
    ("💾 Backups & Snapshots", "backups", "Export, import, and versioned backups"),
    ("📜 Audit & Health", "audit", "Permission audit and guided security fixes"),
]


class DashboardView(ui.View):
    """Unified administrator control center."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild, user_id: int, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.user_id = user_id
        self.current_section: str = "builder"
        self._rebuild_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the administrator who opened the dashboard can use it.", ephemeral=True)
            return False
        return True

    def _rebuild_controls(self) -> None:
        self.clear_items()

        # Section Selector (Row 0)
        options = [
            discord.SelectOption(
                label=name,
                value=key,
                description=desc[:100],
                default=(self.current_section == key),
            )
            for name, key, desc in SECTIONS
        ]
        select = ui.Select(
            placeholder="Select a Control Panel Section...",
            options=options,
            row=0,
        )
        select.callback = self._on_section_select
        self.add_item(select)

        # Context-sensitive action buttons based on selected section (Row 1)
        if self.current_section == "builder":
            btn1 = ui.Button(label="➕ Create Channel", style=discord.ButtonStyle.primary, row=1)
            btn1.callback = self._on_create_channel
            self.add_item(btn1)

            btn2 = ui.Button(label="📁 Create Category", style=discord.ButtonStyle.secondary, row=1)
            btn2.callback = self._on_create_category
            self.add_item(btn2)

        elif self.current_section == "audit":
            btn = ui.Button(label="🔍 Run Server Audit", style=discord.ButtonStyle.primary, row=1)
            btn.callback = self._on_run_audit
            self.add_item(btn)

        elif self.current_section == "backups":
            btn = ui.Button(label="📸 Take Snapshot", style=discord.ButtonStyle.success, row=1)
            btn.callback = self._on_take_snapshot
            self.add_item(btn)

    async def _on_section_select(self, interaction: discord.Interaction) -> None:
        self.current_section = interaction.data["values"][0]  # type: ignore
        self._rebuild_controls()
        embed = await self.get_section_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_create_channel(self, interaction: discord.Interaction) -> None:
        view = InteractiveChannelBuilderView(self.guild, self.user_id)
        await interaction.response.send_message(embed=view.build_preview_embed(), view=view, ephemeral=True)

    async def _on_create_category(self, interaction: discord.Interaction) -> None:
        view = InteractiveCategoryBuilderView(self.guild, self.user_id)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    async def _on_run_audit(self, interaction: discord.Interaction) -> None:
        report = run_server_audit(self.guild)
        await interaction.response.send_message(embed=report.summary_embed(self.guild.name), ephemeral=True)

    async def _on_take_snapshot(self, interaction: discord.Interaction) -> None:
        from builder.snapshot import take_guild_snapshot
        repo = SnapshotRepository()
        snapshot_dict = take_guild_snapshot(self.guild)
        snap_id = await repo.create_snapshot(self.guild.id, self.user_id, f"Dashboard Snapshot", snapshot_dict)
        await interaction.response.send_message(
            embed=success_embed("Snapshot Saved", f"Captured Snapshot **#{snap_id}**."),
            ephemeral=True,
        )

    async def get_section_embed(self) -> discord.Embed:
        sec = self.current_section

        if sec == "builder":
            embed = info_embed(
                "🏗️ Damu Server Builder",
                "Easily generate, customize, or plan your entire server structure.\n\n"
                "**Available Commands:**\n"
                "• `/setup_server` — Build from curated preset templates\n"
                "• `/create_channel` — Interactive wizard for Text, Voice, Forum, Stage, Announcement\n"
                "• `/create_category` — Interactive category setup with permission presets\n"
                "• `/clone_channel` / `/clone_category` — Duplicate existing channels/categories\n"
                "• `/setup_custom` / `/setup_paste_json` — Build from your custom JSON template\n"
                "• `/build_preview` — Side-effect-free preflight check & plan",
            )
        elif sec == "permissions":
            embed = info_embed(
                "🔐 Permission Controls",
                "Granular three-state permission management (`Allow`, `Deny`, `Inherit`).\n\n"
                "**Available Commands:**\n"
                "• `/channel_permissions` — Interactive 3-state permission editor with toggles\n"
                "• `/permission_matrix` — Visual matrix grid of roles vs key permissions\n"
                "• `/perm_sync_check` — Check live permissions against schema/template",
            )
        elif sec == "roles":
            embed = info_embed(
                "🎭 Role Management",
                "Create, customize, and maintain roles with built-in hierarchy validation.\n\n"
                "**Available Commands:**\n"
                "• `/create_role` — Create roles with presets (Admin, Moderator, VIP, Creator...)\n"
                "• `/edit_role` — Adjust role color, hoist, and mentionable status safely\n"
                "• `/delete_role` — Delete a role with hierarchy check protection",
            )
        elif sec == "categories":
            embed = info_embed(
                "📁 Category Management",
                "Organize your server layout into structured categories with inheritance.\n\n"
                "**Available Commands:**\n"
                "• `/create_category` — Create a new category with presets and channel wizard\n"
                "• `/clone_category` — Duplicate an entire category and all of its channels",
            )
        elif sec == "channels":
            embed = info_embed(
                "💬 Channel Management",
                "Full support for Text, Voice, Forum, Stage, and Announcement channels.\n\n"
                "**Available Commands:**\n"
                "• `/create_channel` — Step-by-step interactive channel creator\n"
                "• `/clone_channel` — Duplicate any channel with all settings\n"
                "• `/channel_summaries` — Post clean channel purpose descriptions",
            )
        elif sec == "automod":
            repo = AutoModRepository()
            cfg = await repo.get_config(self.guild.id)
            status_lines = [
                f"• Bad Words Filter: `{'Enabled' if cfg.get('badwords_enabled') else 'Disabled'}`",
                f"• Link Filter: `{'Enabled' if cfg.get('links_enabled') else 'Disabled'}`",
                f"• Invite Filter: `{'Enabled' if cfg.get('invites_enabled') else 'Disabled'}`",
                f"• Anti-Spam: `{'Enabled' if cfg.get('spam_enabled') else 'Disabled'}`",
                f"• Anti-Caps: `{'Enabled' if cfg.get('caps_enabled') else 'Disabled'}`",
            ]
            embed = info_embed(
                "🛡️ AutoMod Protection",
                "Automated chat moderation and spam prevention.\n\n" + "\n".join(status_lines) +
                "\n\n**Configuration:** Use `/automod` to toggle filters and manage bad words.",
            )
        elif sec == "verification":
            embed = info_embed(
                "✅ Member Verification",
                "Gatekeep your server with captcha/button verification to prevent raids.\n\n"
                "**Commands:**\n"
                "• `/verification_setup` — Deploy an interactive verification embed\n"
                "• `/verify` — Manual verification fallback command",
            )
        elif sec == "tickets":
            repo = TicketRepository()
            cfg = await repo.get_config(self.guild.id)
            embed = info_embed(
                "🎫 Support Tickets",
                f"Status: `{'Configured' if cfg else 'Not configured'}`\n\n"
                "**Commands:**\n"
                "• `/ticket_setup` — Deploy a support ticket creation panel\n"
                "• `/ticket close` — Close and archive a ticket channel with transcript",
            )
        elif sec == "welcome":
            embed = info_embed(
                "👋 Welcome & Goodbye",
                "Greet new members and post departure logs.\n\n"
                "**Commands:**\n"
                "• `/welcome_channel` — Set the welcome notification channel\n"
                "• `/goodbye_channel` — Set the farewell log channel",
            )
        elif sec == "moderation":
            embed = info_embed(
                "🔨 Moderation Suite",
                "Enforce rules with warnings, mutes, kicks, and bans.\n\n"
                "**Commands:**\n"
                "• `/warn` / `/warnings` — Track member infractions\n"
                "• `/timeout` / `/kick` / `/ban` — Apply moderation penalties\n"
                "• `/clear` — Purge unwanted messages in bulk",
            )
        elif sec == "analytics":
            embed = info_embed(
                "📊 Server Analytics",
                "Real-time insight into server activity and growth.\n\n"
                "**Commands:**\n"
                "• `/stats` — View server-wide message and voice statistics\n"
                "• `/leaderboard` — Most active chatters and voice participants",
            )
        elif sec == "ai":
            embed = info_embed(
                "🤖 AI Assistant & Editor",
                "Gemini-powered natural language server configuration.\n\n"
                "**Commands:**\n"
                "• `/ai_edit_server` — Natural language instructions (e.g. *'make #announcements read-only'*)\n"
                "• `/generate_server` — Generate an entire themed server from a prompt\n"
                "• `/ai` — Ask AI questions about Discord administration and setup",
            )
        elif sec == "backups":
            repo = SnapshotRepository()
            snaps = await repo.list_snapshots(self.guild.id)
            embed = info_embed(
                "💾 Backups & Snapshots",
                f"Saved Snapshots: **{len(snaps)}**\n\n"
                "**Commands:**\n"
                "• `/server_snapshot` — Capture current server layout\n"
                "• `/snapshot_list` — View all versioned backups\n"
                "• `/snapshot_restore` — Restore a layout safely with preflight preview\n"
                "• `/server_export` / `/server_import` — Download or upload JSON backups",
            )
        elif sec == "audit":
            embed = info_embed(
                "📜 Audit & Health",
                "Scan permissions, bot hierarchy, and security flaws.\n\n"
                "**Commands:**\n"
                "• `/server_audit` — Security scan with Critical, Warning, and Healthy metrics\n"
                "• `/server_fix` — Guided automated remediations for detected vulnerabilities\n"
                "• `/build_history` / `/build_rollback` — Inspect and revert past builds",
            )
        else:
            embed = info_embed("Dashboard", "Select a section from the dropdown menu above.")

        embed.set_footer(text=f"Damu Control Center • {self.guild.name}")
        return embed


class CommandCenterCog(commands.Cog, name="Command Center"):
    """Unified interactive management dashboard for Discord administrators."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="dashboard",
        description="Open the Damu Server Builder & Management interactive control center.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        view = DashboardView(self.bot, interaction.guild, interaction.user.id)
        embed = await view.get_section_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommandCenterCog(bot))
