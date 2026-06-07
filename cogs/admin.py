"""Owner-only bot administration commands."""

from __future__ import annotations

import pathlib

import discord
from discord import app_commands
from discord.ext import commands

from services.embed_service import error_embed, info_embed, success_embed


async def _owner_only(interaction: discord.Interaction) -> bool:
    if await interaction.client.is_owner(interaction.user):
        return True

    embed = error_embed("Owner Only", "You do not have permission to use this command.")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)
    return False


class AdminCog(commands.Cog, name="Admin"):
    """Manual sync, reload, diagnostics, and shutdown commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _reload_extension(self, ext: str) -> tuple[bool, str]:
        try:
            if ext in self.bot.extensions:
                await self.bot.reload_extension(ext)
            else:
                await self.bot.load_extension(ext)
            if hasattr(self.bot, "failed_cogs"):
                self.bot.failed_cogs.pop(ext, None)  # type: ignore[attr-defined]
            return True, f"Reloaded `{ext}`"
        except Exception as exc:
            if hasattr(self.bot, "failed_cogs"):
                self.bot.failed_cogs[ext] = str(exc)  # type: ignore[attr-defined]
            return False, f"Failed `{ext}`: `{exc}`"

    @app_commands.command(name="sync", description="Owner only: sync slash commands globally or to this guild.")
    @app_commands.describe(scope="Use guild for instant testing, global for production updates")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Guild", value="guild"),
            app_commands.Choice(name="Global", value="global"),
        ]
    )
    async def sync(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await _owner_only(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        selected = scope.value if scope else "global"
        if selected == "guild":
            if not interaction.guild:
                return await interaction.followup.send(
                    embed=error_embed("Guild Required", "Run guild sync inside a server."),
                    ephemeral=True,
                )
            synced = await self.bot.tree.sync(guild=interaction.guild)
            embed = success_embed(
                "Guild Sync Complete",
                f"Synced **{len(synced)}** slash commands to **{interaction.guild.name}**.",
            )
        else:
            synced = await self.bot.tree.sync()
            embed = success_embed(
                "Global Sync Complete",
                f"Synced **{len(synced)}** slash commands globally. Discord may take time to show updates.",
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="reload", description="Owner only: reload one cog or all cogs.")
    @app_commands.describe(cog_name="Cog file name, extension path, or all")
    async def reload(self, interaction: discord.Interaction, cog_name: str) -> None:
        if not await _owner_only(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if cog_name.lower() == "all":
            results: list[str] = []
            cog_dir = pathlib.Path("cogs")
            for cog_file in sorted(cog_dir.glob("*.py")):
                if cog_file.name.startswith("_") or cog_file.name == "__init__.py":
                    continue
                ok, message = await self._reload_extension(f"cogs.{cog_file.stem}")
                results.append(("[OK] " if ok else "[FAIL] ") + message)
            text = "\n".join(results) or "No cogs found."
            if len(text) > 3900:
                text = text[:3900] + "\n..."
            return await interaction.followup.send(embed=info_embed("Reload All", text), ephemeral=True)

        ext = cog_name if cog_name.startswith("cogs.") else f"cogs.{cog_name}"
        ok, message = await self._reload_extension(ext)
        embed = success_embed("Cog Reloaded", message) if ok else error_embed("Reload Failed", message)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="cogs", description="Owner only: list loaded and failed cogs.")
    async def cogs(self, interaction: discord.Interaction) -> None:
        if not await _owner_only(interaction):
            return

        loaded = sorted(self.bot.extensions.keys())
        failed = getattr(self.bot, "failed_cogs", {})

        loaded_text = "\n".join(f"[OK] `{name}`" for name in loaded) or "None"
        failed_text = "\n".join(f"[FAIL] `{name}`: {reason}" for name, reason in failed.items()) or "None"
        text = f"**Loaded**\n{loaded_text}\n\n**Failed**\n{failed_text}"
        if len(text) > 3900:
            text = text[:3900] + "\n..."
        await interaction.response.send_message(embed=info_embed("Cog Status", text), ephemeral=True)

    @app_commands.command(name="shutdown", description="Owner only: gracefully shut down the bot.")
    async def shutdown(self, interaction: discord.Interaction) -> None:
        if not await _owner_only(interaction):
            return

        await interaction.response.send_message(
            embed=success_embed("Shutting Down", "Closing the Discord connection now."),
            ephemeral=True,
        )
        await self.bot.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
