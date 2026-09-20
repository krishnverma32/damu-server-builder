"""Interactive UI views and modals for creating channels and categories."""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord import ui

from builder.permissions import (
    PERMISSION_PRESETS,
    _resolve_permissions,
    tri_state_to_overwrite,
)
from builder.permission_views import PermissionEditorView
from services.embed_service import error_embed, info_embed, success_embed

log = logging.getLogger(__name__)


class ChannelSettingsModal(ui.Modal, title="Channel Details"):
    """Modal to enter channel name, topic, slowmode, and NSFW settings."""

    channel_name = ui.TextInput(
        label="Channel Name",
        placeholder="e.g. general, clips, announcements",
        max_length=100,
        required=True,
    )
    topic = ui.TextInput(
        label="Channel Topic / Description",
        placeholder="What is this channel for?",
        max_length=1024,
        required=False,
    )
    slowmode = ui.TextInput(
        label="Slowmode Delay (seconds, 0 for none)",
        placeholder="0",
        default="0",
        max_length=5,
        required=False,
    )
    nsfw = ui.TextInput(
        label="Age-Restricted / NSFW (yes / no)",
        placeholder="no",
        default="no",
        max_length=5,
        required=False,
    )

    def __init__(self, parent_view: "InteractiveChannelBuilderView") -> None:
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = str(self.channel_name).strip().lower().replace(" ", "-")
        topic_val = str(self.topic).strip()
        try:
            slowmode_sec = int(str(self.slowmode).strip() or "0")
        except ValueError:
            slowmode_sec = 0

        is_nsfw = str(self.nsfw).strip().lower() in ("yes", "y", "true", "1")

        self.parent_view.channel_name = name
        self.parent_view.topic = topic_val
        self.parent_view.slowmode = slowmode_sec
        self.parent_view.nsfw = is_nsfw

        embed = self.parent_view.build_preview_embed()
        self.parent_view._rebuild_controls()
        await interaction.response.edit_message(embed=embed, view=self.parent_view)


class InteractiveChannelBuilderView(ui.View):
    """Step-by-step wizard for creating any channel in any category."""

    def __init__(
        self,
        guild: discord.Guild,
        user_id: int,
        initial_category: discord.CategoryChannel | None = None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild = guild
        self.user_id = user_id
        self.selected_category: discord.CategoryChannel | None = initial_category
        self.channel_type: str = "text"  # text, voice, forum, stage, announcement
        self.channel_name: str = ""
        self.topic: str = ""
        self.slowmode: int = 0
        self.nsfw: bool = False
        self.inherit_category_permissions: bool = True
        self.overwrites_data: dict[str, dict[str, bool | None]] = {}
        self.created_channel: discord.abc.GuildChannel | None = None

        self._rebuild_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the creator can interact with this builder.", ephemeral=True)
            return False
        return True

    def _rebuild_controls(self) -> None:
        self.clear_items()

        # 1. Category select dropdown (Row 0)
        cat_options: list[discord.SelectOption] = [
            discord.SelectOption(
                label="[ No Category / Root ]",
                value="none",
                default=(self.selected_category is None),
                description="Place channel at the server root",
            )
        ]
        for cat in self.guild.categories[:23]:
            cat_options.append(
                discord.SelectOption(
                    label=cat.name[:100],
                    value=str(cat.id),
                    default=(self.selected_category is not None and self.selected_category.id == cat.id),
                    description=f"{len(cat.channels)} existing channels",
                )
            )

        cat_select = ui.Select(
            placeholder="Select Category...",
            options=cat_options,
            row=0,
        )
        cat_select.callback = self._on_category_select
        self.add_item(cat_select)

        # 2. Channel type select dropdown (Row 1)
        type_options = [
            discord.SelectOption(
                label="Text Channel",
                value="text",
                description="Standard text & media messages",
                default=(self.channel_type == "text"),
                emoji="💬",
            ),
            discord.SelectOption(
                label="Voice Channel",
                value="voice",
                description="Voice & video hangout room",
                default=(self.channel_type == "voice"),
                emoji="🔊",
            ),
            discord.SelectOption(
                label="Announcement Channel",
                value="announcement",
                description="Broadcast news to members and followers",
                default=(self.channel_type == "announcement"),
                emoji="📢",
            ),
            discord.SelectOption(
                label="Forum Channel",
                value="forum",
                description="Organized topic-based discussions & threads",
                default=(self.channel_type == "forum"),
                emoji="📋",
            ),
            discord.SelectOption(
                label="Stage Channel",
                value="stage",
                description="Live audio events with speakers and listeners",
                default=(self.channel_type == "stage"),
                emoji="🎭",
            ),
        ]
        type_select = ui.Select(
            placeholder="Select Channel Type...",
            options=type_options,
            row=1,
        )
        type_select.callback = self._on_type_select
        self.add_item(type_select)

        # 3. Settings Modal Button (Row 2)
        settings_btn = ui.Button(
            label="✏ Edit Details (Name, Topic, Slowmode)",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        settings_btn.callback = self._on_edit_details
        self.add_item(settings_btn)

        # 4. Permissions Button & Presets (Row 2 & 3)
        perm_btn = ui.Button(
            label="🔐 Custom Permissions",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        perm_btn.callback = self._on_custom_perms
        self.add_item(perm_btn)

        preset_options = [
            discord.SelectOption(label=p, value=p)
            for p in ["Public Chat", "Read Only", "Announcement", "Staff Only", "Admin Only", "VIP Only", "Media"]
        ]
        preset_select = ui.Select(
            placeholder="Apply Channel Permission Preset...",
            options=preset_options,
            row=3,
        )
        preset_select.callback = self._on_preset_select
        self.add_item(preset_select)

        # 5. Create & Cancel Action Buttons (Row 4)
        create_btn = ui.Button(
            label="✅ Create Channel",
            style=discord.ButtonStyle.success,
            disabled=not bool(self.channel_name),
            row=4,
        )
        create_btn.callback = self._on_confirm_create
        self.add_item(create_btn)

        cancel_btn = ui.Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.danger,
            row=4,
        )
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

    async def _on_category_select(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]  # type: ignore
        if val == "none":
            self.selected_category = None
        else:
            self.selected_category = self.guild.get_channel(int(val))  # type: ignore
        self._rebuild_controls()
        await interaction.response.edit_message(embed=self.build_preview_embed(), view=self)

    async def _on_type_select(self, interaction: discord.Interaction) -> None:
        self.channel_type = interaction.data["values"][0]  # type: ignore
        self._rebuild_controls()
        await interaction.response.edit_message(embed=self.build_preview_embed(), view=self)

    async def _on_edit_details(self, interaction: discord.Interaction) -> None:
        modal = ChannelSettingsModal(self)
        if self.channel_name:
            modal.channel_name.default = self.channel_name
        if self.topic:
            modal.topic.default = self.topic
        modal.slowmode.default = str(self.slowmode)
        modal.nsfw.default = "yes" if self.nsfw else "no"
        await interaction.response.send_modal(modal)

    async def _on_custom_perms(self, interaction: discord.Interaction) -> None:
        async def save_perms(new_data: dict[str, dict[str, bool | None]]) -> None:
            self.overwrites_data = new_data
            self.inherit_category_permissions = False

        editor_view = PermissionEditorView(
            guild=self.guild,
            target_name="@everyone",
            current_overwrites=self.overwrites_data,
            on_save=save_perms,
        )
        await interaction.response.send_message(
            embed=editor_view.get_embed(),
            view=editor_view,
            ephemeral=True,
        )

    async def _on_preset_select(self, interaction: discord.Interaction) -> None:
        preset_name = interaction.data["values"][0]  # type: ignore
        preset = PERMISSION_PRESETS.get(preset_name, {})
        self.overwrites_data = {}
        for tgt, rules in preset.items():
            self.overwrites_data[tgt] = {}
            for p in rules.get("allow", []):
                self.overwrites_data[tgt][p] = True
            for p in rules.get("deny", []):
                self.overwrites_data[tgt][p] = False
        self.inherit_category_permissions = False
        await interaction.response.edit_message(
            embed=self.build_preview_embed(),
            view=self,
        )

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore
        await interaction.response.edit_message(
            embed=info_embed("Channel Creation Cancelled", "No channel was created."),
            view=self,
        )
        self.stop()

    async def _on_confirm_create(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
        if not self.inherit_category_permissions and self.overwrites_data:
            for tgt, state in self.overwrites_data.items():
                target_obj: discord.Role | discord.Member | None = None
                if tgt == "@everyone":
                    target_obj = self.guild.default_role
                elif tgt.startswith("role:"):
                    target_obj = discord.utils.get(self.guild.roles, name=tgt[5:])
                elif tgt.startswith("member:"):
                    target_obj = self.guild.get_member(int(tgt[7:]))
                else:
                    target_obj = discord.utils.get(self.guild.roles, name=tgt)
                if target_obj:
                    overwrites[target_obj] = tri_state_to_overwrite(state)

        try:
            if self.channel_type == "voice":
                ch = await self.guild.create_voice_channel(
                    name=self.channel_name,
                    category=self.selected_category,
                    overwrites=overwrites or None,  # type: ignore
                )
            elif self.channel_type == "stage":
                ch = await self.guild.create_stage_channel(
                    name=self.channel_name,
                    category=self.selected_category,
                    topic=self.topic,
                    overwrites=overwrites or None,  # type: ignore
                )
            elif self.channel_type == "announcement":
                is_news = "COMMUNITY" in self.guild.features
                ch = await self.guild.create_text_channel(
                    name=self.channel_name,
                    category=self.selected_category,
                    topic=self.topic,
                    slowmode_delay=self.slowmode,
                    nsfw=self.nsfw,
                    news=is_news,
                    overwrites=overwrites or None,  # type: ignore
                )
            elif self.channel_type == "forum":
                if "COMMUNITY" not in self.guild.features:
                    return await interaction.followup.send(
                        embed=error_embed(
                            "Community Required",
                            "Forum channels require **Community** to be enabled in Server Settings before they can be created.",
                        ),
                        ephemeral=True,
                    )
                ch = await self.guild.create_forum(
                    name=self.channel_name,
                    category=self.selected_category,
                    topic=self.topic,
                    slowmode_delay=self.slowmode,
                    nsfw=self.nsfw,
                    overwrites=overwrites or None,  # type: ignore
                )
            else:
                ch = await self.guild.create_text_channel(
                    name=self.channel_name,
                    category=self.selected_category,
                    topic=self.topic,
                    slowmode_delay=self.slowmode,
                    nsfw=self.nsfw,
                    overwrites=overwrites or None,  # type: ignore
                )

            self.created_channel = ch
            for item in self.children:
                item.disabled = True  # type: ignore

            await interaction.followup.send(
                embed=success_embed(
                    "Channel Created!",
                    f"Successfully created **{ch.mention}** under **{self.selected_category.name if self.selected_category else '[Root]'}**.",
                ),
                ephemeral=True,
            )
            self.stop()
        except Exception as exc:
            log.exception("Interactive channel creation failed: %s", exc)
            await interaction.followup.send(
                embed=error_embed("Failed to Create Channel", f"Discord rejected channel creation: {exc}"),
                ephemeral=True,
            )

    def build_preview_embed(self) -> discord.Embed:
        embed = info_embed(
            "🏗 Interactive Channel Builder",
            "Configure your channel settings below. Once you are satisfied, click **Create Channel**.",
        )
        cat_name = self.selected_category.name if self.selected_category else "*[Root / No Category]*"
        name_display = f"`#{self.channel_name}`" if self.channel_name else "*Not set yet (click Edit Details)*"
        embed.add_field(name="Category", value=cat_name, inline=True)
        embed.add_field(name="Type", value=self.channel_type.title(), inline=True)
        embed.add_field(name="Name", value=name_display, inline=True)
        embed.add_field(name="Topic", value=self.topic or "*None*", inline=False)
        embed.add_field(
            name="Settings",
            value=f"Slowmode: `{self.slowmode}s` | NSFW: `{'Yes' if self.nsfw else 'No'}`",
            inline=True,
        )

        if self.inherit_category_permissions:
            perm_str = "● Inheriting Category Permissions"
        else:
            perm_str = f"○ Custom Overwrites ({len(self.overwrites_data)} targets configured)"
        embed.add_field(name="Permissions", value=perm_str, inline=True)

        return embed


class InteractiveCategoryBuilderView(ui.View):
    """Interactive category creator with immediate option to add channels."""

    def __init__(
        self,
        guild: discord.Guild,
        user_id: int,
        category_name: str = "",
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild = guild
        self.user_id = user_id
        self.category_name = category_name
        self.overwrites_data: dict[str, dict[str, bool | None]] = {}
        self.created_category: discord.CategoryChannel | None = None
        self._rebuild_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the creator can interact with this view.", ephemeral=True)
            return False
        return True

    def _rebuild_controls(self) -> None:
        self.clear_items()

        # Preset selector for category permissions
        preset_select = ui.Select(
            placeholder="Apply Category Permission Preset...",
            options=[
                discord.SelectOption(label=p, value=p)
                for p in ["Public Chat", "Read Only", "Staff Only", "Admin Only", "VIP Only", "Private"]
            ],
            row=0,
        )
        preset_select.callback = self._on_preset_select
        self.add_item(preset_select)

        # Custom perms button
        perms_btn = ui.Button(label="🔐 Edit Permissions", style=discord.ButtonStyle.secondary, row=1)
        perms_btn.callback = self._on_custom_perms
        self.add_item(perms_btn)

        # Create Category button
        create_btn = ui.Button(label="✅ Create Category", style=discord.ButtonStyle.success, row=1)
        create_btn.callback = self._on_create_category
        self.add_item(create_btn)

        cancel_btn = ui.Button(label="❌ Cancel", style=discord.ButtonStyle.danger, row=1)
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

    async def _on_preset_select(self, interaction: discord.Interaction) -> None:
        preset_name = interaction.data["values"][0]  # type: ignore
        preset = PERMISSION_PRESETS.get(preset_name, {})
        self.overwrites_data = {}
        for tgt, rules in preset.items():
            self.overwrites_data[tgt] = {}
            for p in rules.get("allow", []):
                self.overwrites_data[tgt][p] = True
            for p in rules.get("deny", []):
                self.overwrites_data[tgt][p] = False
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _on_custom_perms(self, interaction: discord.Interaction) -> None:
        async def save_perms(new_data: dict[str, dict[str, bool | None]]) -> None:
            self.overwrites_data = new_data

        editor = PermissionEditorView(
            guild=self.guild,
            target_name="@everyone",
            current_overwrites=self.overwrites_data,
            on_save=save_perms,
        )
        await interaction.response.send_message(embed=editor.get_embed(), view=editor, ephemeral=True)

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore
        await interaction.response.edit_message(
            embed=info_embed("Cancelled", "Category creation cancelled."), view=self
        )
        self.stop()

    async def _on_create_category(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
        for tgt, state in self.overwrites_data.items():
            target_obj: discord.Role | discord.Member | None = None
            if tgt == "@everyone":
                target_obj = self.guild.default_role
            elif tgt.startswith("role:"):
                target_obj = discord.utils.get(self.guild.roles, name=tgt[5:])
            elif tgt.startswith("member:"):
                target_obj = self.guild.get_member(int(tgt[7:]))
            else:
                target_obj = discord.utils.get(self.guild.roles, name=tgt)
            if target_obj:
                overwrites[target_obj] = tri_state_to_overwrite(state)

        try:
            cat = await self.guild.create_category(
                name=self.category_name,
                overwrites=overwrites or None,  # type: ignore
            )
            self.created_category = cat

            # Post-creation follow-up view
            followup_view = CategoryPostCreateView(cat, self.user_id)
            await interaction.followup.send(
                embed=success_embed(
                    "Category Created!",
                    f"Successfully created **{cat.name}**.\nWould you like to add channels now?",
                ),
                view=followup_view,
                ephemeral=True,
            )
            self.stop()
        except Exception as exc:
            log.exception("Category creation failed: %s", exc)
            await interaction.followup.send(
                embed=error_embed("Failed to Create Category", str(exc)), ephemeral=True
            )

    def get_embed(self) -> discord.Embed:
        embed = info_embed(
            "📁 Create Category",
            f"Configuring category **{self.category_name}**.",
        )
        embed.add_field(
            name="Permissions",
            value=f"{len(self.overwrites_data)} target overrides configured" if self.overwrites_data else "Default server permissions",
            inline=False,
        )
        return embed


class CategoryPostCreateView(ui.View):
    """View shown after a category is created to quickly add channels."""

    def __init__(self, category: discord.CategoryChannel, user_id: int, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.category = category
        self.user_id = user_id

    @ui.button(label="➕ Add Channel to Category", style=discord.ButtonStyle.primary)
    async def add_channel(self, interaction: discord.Interaction, button: ui.Button) -> None:
        channel_view = InteractiveChannelBuilderView(
            guild=self.category.guild,
            user_id=self.user_id,
            initial_category=self.category,
        )
        await interaction.response.send_message(
            embed=channel_view.build_preview_embed(),
            view=channel_view,
            ephemeral=True,
        )
        self.stop()

    @ui.button(label="✅ Finished", style=discord.ButtonStyle.secondary)
    async def finish(self, interaction: discord.Interaction, button: ui.Button) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore
        await interaction.response.edit_message(
            embed=success_embed("Done", f"Category **{self.category.name}** is ready."), view=self
        )
        self.stop()
