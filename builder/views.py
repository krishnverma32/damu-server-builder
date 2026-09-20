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
