"""Dashboard/admin cog - welcome, auto-role, command channel, mass roles."""

from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Literal

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from services.embed_service import error_embed, info_embed, success_embed

log = logging.getLogger("cogs.dashboard")

RuleTarget = Literal["all", "humans", "bots"]

DEFAULT_RULES = [
    "1. Respect everyone.",
    "2. No spam or harassment.",
    "3. Follow Discord Terms of Service.",
]

WELCOME_ASSETS_DIR = Path(config.DATA_DIR) / "welcome_assets"
WELCOME_IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _default_guild_config() -> dict[str, Any]:
    return {
        "welcome": {
            "channel_id": 0,
            "title": "Welcome to {server}!",
            "description": "Glad to have you here, {member}.",
            "footer": "Enjoy your stay.",
            "thumbnail_url": "",
            "banner_url": "",
            "banner_file": "",
            "use_giphy": False,
            "giphy_query": "welcome discord",
        },
        "auto_roles": {
            "human_role_id": 0,
            "bot_role_id": 0,
        },
        "commands_channel_id": 0,
    }


class DashboardCog(commands.Cog, name="Dashboard"):
    """Server dashboard controls exposed as slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._config_cache: dict[str, Any] | None = None

    def _load_all(self) -> dict[str, Any]:
        if self._config_cache is not None:
            return self._config_cache

        if os.path.exists(config.DASHBOARD_CONFIG_FILE):
            try:
                with open(config.DASHBOARD_CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config_cache = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._config_cache = {}
        else:
            self._config_cache = {}

        return self._config_cache

    def _save_all(self) -> None:
        os.makedirs(os.path.dirname(config.DASHBOARD_CONFIG_FILE), exist_ok=True)
        with open(config.DASHBOARD_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._load_all(), f, indent=2)

    def _guild_config(self, guild_id: int) -> dict[str, Any]:
        all_config = self._load_all()
        key = str(guild_id)
        if key not in all_config:
            all_config[key] = _default_guild_config()
        return all_config[key]

    async def _random_giphy_url(self, query: str) -> str:
        if not config.GIPHY_API_KEY:
            return ""

        params = {
            "api_key": config.GIPHY_API_KEY,
            "q": query or "welcome discord",
            "limit": 25,
            "rating": "pg",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.giphy.com/v1/gifs/search", params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return ""
                    data = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            return ""

        gifs = data.get("data", [])
        if not gifs:
            return ""
        item = random.choice(gifs)
        return (
            item.get("images", {})
            .get("original", {})
            .get("url", "")
        )

    async def _save_welcome_image(self, guild_id: int, image: discord.Attachment) -> str:
        content_type = (image.content_type or "").split(";")[0].lower()
        extension = WELCOME_IMAGE_EXTENSIONS.get(content_type)
        if extension is None:
            lower_name = image.filename.lower()
            extension = next(
                (ext for ext in WELCOME_IMAGE_EXTENSIONS.values() if lower_name.endswith(ext)),
                "",
            )
        if not extension:
            raise ValueError("Unsupported image type. Use PNG, JPG, WEBP, or GIF.")

        WELCOME_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = WELCOME_ASSETS_DIR / f"{guild_id}{extension}"
        await image.save(file_path)
        return str(file_path)

    @staticmethod
    def _format_welcome_text(text: str, member: discord.Member) -> str:
        return (
            text.replace("{member}", member.mention)
            .replace("{user}", member.display_name)
            .replace("{server}", member.guild.name)
            .replace("{count}", str(member.guild.member_count or 0))
        )

    async def _apply_join_role(self, member: discord.Member, role_id: int, reason: str) -> bool:
        if not role_id:
            return False

        role = member.guild.get_role(role_id)
        if not role or role >= member.guild.me.top_role:  # type: ignore[union-attr]
            return False

        try:
            await member.add_roles(role, reason=reason)
            return True
        except discord.HTTPException:
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild_config = self._guild_config(member.guild.id)
        auto_roles = guild_config.get("auto_roles", {})
        role_id = auto_roles.get("bot_role_id" if member.bot else "human_role_id", 0)
        await self._apply_join_role(member, role_id, "Dashboard auto-role")

        welcome = guild_config.get("welcome", {})
        channel_id = welcome.get("channel_id", 0)
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title=self._format_welcome_text(welcome.get("title", "Welcome!"), member),
            description=self._format_welcome_text(welcome.get("description", ""), member),
            colour=config.BOT_COLOR,
        )
        embed.add_field(name="Server Rules", value="\n".join(DEFAULT_RULES), inline=False)

        footer = welcome.get("footer", "")
        if footer:
            embed.set_footer(text=self._format_welcome_text(footer, member))

        thumbnail_url = welcome.get("thumbnail_url", "")
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        else:
            embed.set_thumbnail(url=member.display_avatar.url)

        image_url = welcome.get("banner_url", "")
        file: discord.File | None = None
        if welcome.get("use_giphy"):
            image_url = await self._random_giphy_url(welcome.get("giphy_query", "welcome discord")) or image_url
        if not image_url and welcome.get("banner_file") and os.path.exists(welcome["banner_file"]):
            file_name = Path(welcome["banner_file"]).name
            file = discord.File(welcome["banner_file"], filename=file_name)
            embed.set_image(url=f"attachment://{file_name}")

        if image_url:
            embed.set_image(url=image_url)

        try:
            await channel.send(content=member.mention, embed=embed, file=file)
        except discord.HTTPException:
            log.warning("Failed to send welcome message in guild %s", member.guild.id)

    @app_commands.command(name="welcome_setup", description="Configure embedded welcome messages.")
    @app_commands.describe(
        channel="Channel where welcome messages are sent",
        title="Embed title. Supports {member}, {user}, {server}, {count}",
        description="Embed message. Supports {member}, {user}, {server}, {count}",
        footer="Footer text",
        thumbnail_url="Optional thumbnail URL",
        image="Optional uploaded banner/welcome image",
        use_giphy="Use random welcome GIFs from GIPHY",
        giphy_query="Search query for random welcome GIFs",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str = "Welcome to {server}!",
        description: str = "Glad to have you here, {member}.",
        footer: str = "Respect everyone and enjoy your stay.",
        thumbnail_url: str = "",
        image: discord.Attachment | None = None,
        use_giphy: bool = False,
        giphy_query: str = "welcome discord",
    ) -> None:
        assert interaction.guild is not None
        current_welcome = self._guild_config(interaction.guild.id).get("welcome", {})
        banner_file = current_welcome.get("banner_file", "")
        if image:
            try:
                banner_file = await self._save_welcome_image(interaction.guild.id, image)
            except (discord.HTTPException, OSError, ValueError) as exc:
                return await interaction.response.send_message(
                    embed=error_embed("Image Upload Failed", str(exc)),
                    ephemeral=True,
                )

        guild_config = self._guild_config(interaction.guild.id)
        guild_config["welcome"] = {
            "channel_id": channel.id,
            "title": title,
            "description": description,
            "footer": footer,
            "thumbnail_url": thumbnail_url,
            "banner_url": "",
            "banner_file": banner_file,
            "use_giphy": use_giphy,
            "giphy_query": giphy_query,
        }
        self._save_all()

        embed = success_embed(
            "Welcome System Updated",
            f"Welcome channel: {channel.mention}\n"
            f"GIPHY: **{'enabled' if use_giphy else 'disabled'}**\n"
            "The embed will ping the new member and include 3 short default rules.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="autorole_setup", description="Configure separate auto roles for humans and bots.")
    @app_commands.describe(
        human_role="Role given to human members when they join",
        bot_role="Role given to bots when they join",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def autorole_setup(
        self,
        interaction: discord.Interaction,
        human_role: discord.Role | None = None,
        bot_role: discord.Role | None = None,
    ) -> None:
        assert interaction.guild is not None
        guild_config = self._guild_config(interaction.guild.id)
        guild_config["auto_roles"] = {
            "human_role_id": human_role.id if human_role else 0,
            "bot_role_id": bot_role.id if bot_role else 0,
        }
        self._save_all()

        await interaction.response.send_message(
            embed=success_embed(
                "Auto Roles Updated",
                f"Humans: {human_role.mention if human_role else '**disabled**'}\n"
                f"Bots: {bot_role.mention if bot_role else '**disabled**'}",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="commands_channel_setup", description="Set the dedicated commands channel.")
    @app_commands.describe(channel="Channel for bot commands")
    @app_commands.checks.has_permissions(administrator=True)
    async def commands_channel_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        assert interaction.guild is not None
        guild_config = self._guild_config(interaction.guild.id)
        guild_config["commands_channel_id"] = channel.id
        self._save_all()
        await interaction.response.send_message(
            embed=success_embed("Commands Channel Set", f"Commands channel: {channel.mention}"),
            ephemeral=True,
        )

    @app_commands.command(name="mass_role", description="Give or remove a role from all, bots, or humans.")
    @app_commands.describe(
        action="Give or remove the role",
        target="Which members should be affected",
        role="Role to give or remove",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Give", value="give"),
            app_commands.Choice(name="Remove", value="remove"),
        ],
        target=[
            app_commands.Choice(name="All Members", value="all"),
            app_commands.Choice(name="Only Humans", value="humans"),
            app_commands.Choice(name="Only Bots", value="bots"),
        ],
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mass_role(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        target: app_commands.Choice[str],
        role: discord.Role,
    ) -> None:
        assert interaction.guild is not None
        if role >= interaction.guild.me.top_role:  # type: ignore[union-attr]
            return await interaction.response.send_message(
                embed=error_embed("Role Too High", "Move my bot role above that role first."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        members = [
            member
            for member in interaction.guild.members
            if target.value == "all"
            or (target.value == "bots" and member.bot)
            or (target.value == "humans" and not member.bot)
        ]

        changed = 0
        failed = 0
        for member in members:
            try:
                if action.value == "give":
                    if role not in member.roles:
                        await member.add_roles(role, reason=f"Mass role by {interaction.user}")
                        changed += 1
                else:
                    if role in member.roles:
                        await member.remove_roles(role, reason=f"Mass role by {interaction.user}")
                        changed += 1
            except discord.HTTPException:
                failed += 1

        await interaction.followup.send(
            embed=success_embed(
                "Mass Role Complete",
                f"Action: **{action.name}**\nTarget: **{target.name}**\nRole: {role.mention}\n"
                f"Changed: **{changed}**\nFailed/skipped: **{failed}**",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="dashboard_status", description="Show dashboard configuration and server overview.")
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard_status(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        guild = interaction.guild
        guild_config = self._guild_config(guild.id)
        welcome = guild_config.get("welcome", {})
        auto_roles = guild_config.get("auto_roles", {})

        humans = sum(1 for member in guild.members if not member.bot)
        bots = sum(1 for member in guild.members if member.bot)
        welcome_channel = guild.get_channel(welcome.get("channel_id", 0))
        commands_channel = guild.get_channel(guild_config.get("commands_channel_id", 0))
        human_role = guild.get_role(auto_roles.get("human_role_id", 0))
        bot_role = guild.get_role(auto_roles.get("bot_role_id", 0))

        embed = info_embed(
            "Moderation Dashboard Overview",
            "Clean control surface for welcome, auto-role, mass roles, commands, and moderation.",
        )
        embed.add_field(name="Members", value=f"Humans: **{humans}**\nBots: **{bots}**", inline=True)
        embed.add_field(name="Channels", value=f"Text: **{len(guild.text_channels)}**\nVoice: **{len(guild.voice_channels)}**", inline=True)
        embed.add_field(name="Roles", value=f"Total: **{len(guild.roles)}**", inline=True)
        embed.add_field(name="Welcome", value=welcome_channel.mention if welcome_channel else "Not set", inline=True)
        embed.add_field(name="Commands", value=commands_channel.mention if commands_channel else "Not set", inline=True)
        embed.add_field(
            name="Auto Roles",
            value=f"Humans: {human_role.mention if human_role else 'Off'}\nBots: {bot_role.mention if bot_role else 'Off'}",
            inline=True,
        )
        embed.add_field(name="Command Categories", value="Moderation\nWelcome\nRoles\nTickets\nUtility\nAI", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DashboardCog(bot))
