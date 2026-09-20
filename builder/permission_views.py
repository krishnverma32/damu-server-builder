"""Interactive three-state Permission Editor and Permission Matrix views."""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

import discord
from discord import ui

from builder.permissions import (
    PERMISSION_CATEGORIES,
    PERMISSION_PRESETS,
    overwrite_to_tri_state,
    tri_state_to_overwrite,
)
from services.embed_service import info_embed, success_embed

log = logging.getLogger(__name__)


class TriStatePermissionButton(ui.Button):
    """Button representing one permission with Allow (✅), Deny (❌), or Inherit (➖)."""

    def __init__(self, perm_name: str, state: bool | None, row: int | None = None) -> None:
        self.perm_name = perm_name
        self.state = state
        label, style = self._display_props(state)
        super().__init__(
            label=f"{label} {perm_name.replace('_', ' ').title()[:18]}",
            style=style,
            row=row,
        )

    def _display_props(self, state: bool | None) -> tuple[str, discord.ButtonStyle]:
        if state is True:
            return "✅", discord.ButtonStyle.success
        if state is False:
            return "❌", discord.ButtonStyle.danger
        return "➖", discord.ButtonStyle.secondary

    def cycle(self) -> bool | None:
        # None -> True -> False -> None
        if self.state is None:
            self.state = True
        elif self.state is True:
            self.state = False
        else:
            self.state = None
        label, style = self._display_props(self.state)
        self.label = f"{label} {self.perm_name.replace('_', ' ').title()[:18]}"
        self.style = style
        return self.state


class PermissionEditorView(ui.View):
    """Administrator-friendly interactive 3-state permission editor."""

    def __init__(
        self,
        guild: discord.Guild,
        target_name: str,
        current_overwrites: dict[str, dict[str, bool | None]],
        on_save: Callable[[dict[str, dict[str, bool | None]]], Coroutine[Any, Any, None]] | None = None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild = guild
        self.current_target = target_name
        self.overwrites_data = current_overwrites  # {target_name: {perm_name: bool | None}}
        self.on_save_callback = on_save
        self.current_category = "GENERAL"
        self._rebuild_controls()

    def _get_target_state(self, target: str) -> dict[str, bool | None]:
        if target not in self.overwrites_data:
            self.overwrites_data[target] = {}
        return self.overwrites_data[target]

    def _rebuild_controls(self) -> None:
        self.clear_items()

        # 1. Target Selector
        target_options: list[discord.SelectOption] = [
            discord.SelectOption(
                label="@everyone",
                value="@everyone",
                default=(self.current_target == "@everyone"),
                description="Default server permissions",
            )
        ]
        for role in self.guild.roles:
            if not role.is_default() and not role.managed:
                target_options.append(
                    discord.SelectOption(
                        label=f"@{role.name}"[:100],
                        value=f"role:{role.name}",
                        default=(self.current_target == f"role:{role.name}"),
                        description=f"Role with {len(role.members)} members",
                    )
                )
        for member in list(self.guild.members)[:15]:
            if not member.bot:
                target_options.append(
                    discord.SelectOption(
                        label=f"User: {member.display_name}"[:100],
                        value=f"member:{member.id}",
                        default=(self.current_target == f"member:{member.id}"),
                        description=f"Direct user override ({member.name})",
                    )
                )

        target_select = ui.Select(
            placeholder="Select Target (@everyone, Role, or Member)...",
            options=target_options[:25],
            row=0,
        )
        target_select.callback = self._on_target_select
        self.add_item(target_select)

        # 2. Category Selector (GENERAL, MESSAGES, MODERATION, VOICE)
        cat_options = [
            discord.SelectOption(
                label=cat,
                value=cat,
                default=(self.current_category == cat),
            )
            for cat in PERMISSION_CATEGORIES
        ]
        cat_select = ui.Select(
            placeholder="Select Permission Group...",
            options=cat_options,
            row=1,
        )
        cat_select.callback = self._on_category_select
        self.add_item(cat_select)

        # 3. Permission buttons for current category
        perms = PERMISSION_CATEGORIES.get(self.current_category, [])
        target_perms = self._get_target_state(self.current_target)

        # Add up to 5 permission buttons per row (rows 2 and 3)
        for idx, perm_name in enumerate(perms[:8]):
            row = 2 if idx < 4 else 3
            state = target_perms.get(perm_name)
            btn = TriStatePermissionButton(perm_name, state, row=row)

            async def _make_callback(b: TriStatePermissionButton, p: str):
                async def _cb(interaction: discord.Interaction):
                    new_val = b.cycle()
                    target_perms[p] = new_val
                    await interaction.response.edit_message(view=self, embed=self.get_embed())
                return _cb

            btn.callback = self._create_button_callback(btn, perm_name, target_perms)
            self.add_item(btn)

        # 4. Presets and Save buttons on row 4
        preset_select = ui.Select(
            placeholder="Apply Preset (Announcement, Staff, VIP...)",
            options=[
                discord.SelectOption(label=p_name, value=p_name)
                for p_name in list(PERMISSION_PRESETS.keys())[:15]
            ],
            row=4,
        )
        preset_select.callback = self._on_preset_select
        self.add_item(preset_select)

    def _create_button_callback(
        self, btn: TriStatePermissionButton, perm_name: str, target_perms: dict[str, bool | None]
    ):
        async def callback(interaction: discord.Interaction):
            new_val = btn.cycle()
            target_perms[perm_name] = new_val
            await interaction.response.edit_message(view=self, embed=self.get_embed())
        return callback

    async def _on_target_select(self, interaction: discord.Interaction) -> None:
        select = interaction.data["values"][0]  # type: ignore
        self.current_target = select
        self._rebuild_controls()
        await interaction.response.edit_message(view=self, embed=self.get_embed())

    async def _on_category_select(self, interaction: discord.Interaction) -> None:
        select = interaction.data["values"][0]  # type: ignore
        self.current_category = select
        self._rebuild_controls()
        await interaction.response.edit_message(view=self, embed=self.get_embed())

    async def _on_preset_select(self, interaction: discord.Interaction) -> None:
        preset_name = interaction.data["values"][0]  # type: ignore
        preset = PERMISSION_PRESETS.get(preset_name, {})
        for tgt, rules in preset.items():
            state = self._get_target_state(tgt)
            for allow_perm in rules.get("allow", []):
                state[allow_perm] = True
            for deny_perm in rules.get("deny", []):
                state[deny_perm] = False
        self._rebuild_controls()
        await interaction.response.edit_message(view=self, embed=self.get_embed())

    def get_embed(self) -> discord.Embed:
        target_display = self.current_target
        if target_display.startswith("role:"):
            target_display = f"@{target_display[5:]}"
        elif target_display.startswith("member:"):
            target_display = f"Member ({target_display[7:]})"

        embed = info_embed(
            f"🔐 Permission Editor — {target_display}",
            "Click any permission button to toggle its state:\n"
            "• **✅ Allow** (Explicit True)\n"
            "• **❌ Deny** (Explicit False)\n"
            "• **➖ Inherit** (Neutral / Inherit Category)",
        )

        state = self._get_target_state(self.current_target)
        summary_lines: list[str] = []
        for cat_name, perms in PERMISSION_CATEGORIES.items():
            configured = []
            for p in perms:
                val = state.get(p)
                if val is True:
                    configured.append(f"✅ `{p}`")
                elif val is False:
                    configured.append(f"❌ `{p}`")
            if configured:
                summary_lines.append(f"**{cat_name}**: " + ", ".join(configured))

        if summary_lines:
            embed.add_field(name="Current Overrides", value="\n".join(summary_lines), inline=False)
        else:
            embed.add_field(name="Current Overrides", value="*(All permissions neutral / inherited)*", inline=False)

        embed.set_footer(text=f"Editing Group: {self.current_category} | Auto-saved in memory")
        return embed

    @ui.button(label="Save & Close", style=discord.ButtonStyle.success, row=4)
    async def save_button(self, interaction: discord.Interaction, button: ui.Button) -> None:
        if self.on_save_callback:
            await self.on_save_callback(self.overwrites_data)
        for item in self.children:
            item.disabled = True  # type: ignore
        await interaction.response.edit_message(
            embed=success_embed("Permissions Saved", "Channel/Category permission overwrites updated successfully."),
            view=self,
        )
        self.stop()


class PermissionMatrixView(ui.View):
    """Paginated matrix showing roles vs key permissions."""

    KEY_PERMISSIONS = [
        ("View", "view_channel"),
        ("Send", "send_messages"),
        ("Files", "attach_files"),
        ("Embed", "embed_links"),
        ("Manage", "manage_messages"),
    ]

    def __init__(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        page: int = 0,
        per_page: int = 6,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild = guild
        self.channel = channel
        self.page = page
        self.per_page = per_page
        self._update_buttons()

    def _get_matrix_data(self) -> tuple[list[tuple[str, list[str]]], int]:
        all_targets: list[tuple[str, discord.PermissionOverwrite]] = []

        # @everyone first
        default_ow = self.channel.overwrites_for(self.guild.default_role)
        all_targets.append(("@everyone", default_ow))

        # Guild roles
        for role in self.guild.roles:
            if not role.is_default() and not role.managed:
                ow = self.channel.overwrites_for(role)
                all_targets.append((role.name, ow))

        total_pages = max(1, (len(all_targets) + self.per_page - 1) // self.per_page)
        start = self.page * self.per_page
        slice_targets = all_targets[start : start + self.per_page]

        rows: list[tuple[str, list[str]]] = []
        for name, ow in slice_targets:
            symbols: list[str] = []
            for _, perm_attr in self.KEY_PERMISSIONS:
                val = getattr(ow, perm_attr, None)
                if val is True:
                    symbols.append("✅")
                elif val is False:
                    symbols.append("❌")
                else:
                    symbols.append("➖")
            rows.append((name[:14], symbols))

        return rows, total_pages

    def _update_buttons(self) -> None:
        _, total_pages = self._get_matrix_data()
        prev_btn: ui.Button = self.prev_page_button  # type: ignore
        next_btn: ui.Button = self.next_page_button  # type: ignore
        prev_btn.disabled = self.page <= 0
        next_btn.disabled = self.page >= total_pages - 1

    def get_embed(self) -> discord.Embed:
        rows, total_pages = self._get_matrix_data()
        header = f"{'Target':<14} | View | Send | Files | Embed | Manage"
        sep = "-" * 50
        lines = [header, sep]

        for name, symbols in rows:
            line = f"{name:<14} |  {symbols[0]}  |  {symbols[1]}  |   {symbols[2]}   |   {symbols[3]}   |   {symbols[4]}"
            lines.append(line)

        matrix_text = "```text\n" + "\n".join(lines) + "\n```"

        embed = info_embed(
            f"📊 Permission Matrix — #{self.channel.name}",
            f"Overview of effective permissions for **{self.channel.mention}**:\n\n{matrix_text}",
        )
        embed.set_footer(text=f"Page {self.page + 1} of {total_pages} | ✅=Allow, ❌=Deny, ➖=Inherit")
        return embed

    @ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_page_button(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_page_button(self, interaction: discord.Interaction, button: ui.Button) -> None:
        _, total_pages = self._get_matrix_data()
        self.page = min(total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
