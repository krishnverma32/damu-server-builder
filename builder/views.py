"""Short-lived, requester-bound confirmation controls for reviewed build plans."""
from __future__ import annotations

import discord


class DestructiveBuildModal(discord.ui.Modal, title="Confirm irreversible cleanup"):
    phrase = discord.ui.TextInput(label="Type CONFIRM DELETE", max_length=30)

    def __init__(self, view: BuildConfirmView) -> None:
        super().__init__(timeout=180)
        self.confirm_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.confirm_view
        if not await view.interaction_check(interaction):
            return
        if str(self.phrase) != "CONFIRM DELETE":
            await interaction.response.send_message("Confirmation did not match. Nothing was changed.", ephemeral=True)
            return
        await view.finish(interaction, True)


class BuildConfirmView(discord.ui.View):
    """The caller removes expired controls after wait(); no persistent mutation buttons."""

    def __init__(self, user_id: int, timeout: float = 180.0, *, destructive: bool = False) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.destructive = destructive
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.is_finished():
            await interaction.response.send_message("This review expired. Start a new setup.", ephemeral=True)
            return False
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the requester can answer this review.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Administrator permission is required to confirm.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction: discord.Interaction, confirmed: bool) -> None:
        self.confirmed = confirmed
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Confirm Build", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.destructive:
            await interaction.response.send_modal(DestructiveBuildModal(self))
        else:
            await self.finish(interaction, True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.finish(interaction, False)


class BuildPreviewView(discord.ui.View):
    """Administrator preview view offering Build, Edit, Permissions, Diff, and Cancel."""

    def __init__(
        self,
        user_id: int,
        guild: discord.Guild,
        schema: dict,
        diff_text: str = "",
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.guild = guild
        self.schema = schema
        self.diff_text = diff_text
        self.action: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.is_finished():
            await interaction.response.send_message("This preview has expired.", ephemeral=True)
            return False
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the requester can interact with this preview.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Build", style=discord.ButtonStyle.success, emoji="✅")
    async def on_build(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.action = "build"
        for child in self.children:
            child.disabled = True  # type: ignore
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Full Diff", style=discord.ButtonStyle.primary, emoji="👀")
    async def on_full_diff(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.diff_text:
            text = self.diff_text if len(self.diff_text) <= 1900 else self.diff_text[:1900] + "\n..."
            await interaction.response.send_message(f"```text\n{text}\n```", ephemeral=True)
        else:
            await interaction.response.send_message("No diff available.", ephemeral=True)

    @discord.ui.button(label="Permissions", style=discord.ButtonStyle.secondary, emoji="🔐")
    async def on_permissions(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from builder.permission_views import PermissionEditorView

        async def _save_dummy(new_overwrites: dict) -> None:
            pass

        editor = PermissionEditorView(
            guild=self.guild,
            target_name="@everyone",
            current_overwrites={},
            on_save=_save_dummy,
        )
        await interaction.response.send_message(embed=editor.get_embed(), view=editor, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def on_cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.action = "cancel"
        for child in self.children:
            child.disabled = True  # type: ignore
        await interaction.response.edit_message(content="Build cancelled.", view=self)
        self.stop()


class RollbackConfirmView(discord.ui.View):
    """Interactive confirmation view for rolling back created build resources."""

    def __init__(self, user_id: int, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.is_finished():
            await interaction.response.send_message("This rollback prompt expired.", ephemeral=True)
            return False
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the requester can answer this rollback prompt.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Rollback", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


