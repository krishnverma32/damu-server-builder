"""Entry point — initialises the bot, loads cogs, and starts the event loop."""

import asyncio
import datetime
import logging
import os
import pathlib

import discord
from aiohttp import web
from discord.ext import commands

import config
from services.database import get_database
from services.view_registry import ViewRegistry
from utils.logger import setup_logging

# ── Ensure data directories exist ────────────────────────────────────────
_DATA_DIRS = [
    "data/memory",
    "data/levels",
    "data/tickets",
    "data/templates",
    "data/verification",
    "data/automod",
]
for _d in _DATA_DIRS:
    pathlib.Path(_d).mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────
setup_logging()
log = logging.getLogger("bot")

if config.SERVER_BUILD_OWNER_ID == 0:
    log.error("SERVER_BUILD_OWNER_ID must be set in .env before startup.")
    raise RuntimeError("SERVER_BUILD_OWNER_ID must be set in .env")

# ── Intents ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = False


class ServerBot(commands.Bot):
    """Custom bot subclass with startup hook."""

    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="/help | v" + config.BOT_VERSION
            ),
        )
        self.start_time: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
        self.failed_cogs: dict[str, str] = {}
        self.db = get_database()
        self.view_registry = ViewRegistry()

    async def setup_hook(self) -> None:
        """Load all cogs dynamically from the cogs/ directory."""
        await self.db.create_tables()
        log.info("SQLite database ready: %s", config.DATABASE_FILE)

        cog_dir = pathlib.Path("cogs")
        for cog_file in cog_dir.glob("*.py"):
            if cog_file.name.startswith("_") or cog_file.name == "__init__.py":
                continue
            ext = f"cogs.{cog_file.stem}"
            try:
                await self.load_extension(ext)
                self.failed_cogs.pop(ext, None)
                log.info("Loaded cog: %s", ext)
            except Exception as exc:
                self.failed_cogs[ext] = str(exc)
                log.error("Failed to load cog %s: %s", ext, exc)

        log.info("Loaded %d extensions. Use /sync to sync slash commands.", len(self.extensions))

    async def on_ready(self) -> None:
        restored = await self.view_registry.restore_all(self)
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)  # type: ignore[union-attr]
        log.info("Guilds: %d | Latency: %.0fms", len(self.guilds), self.latency * 1000)
        if restored:
            log.info("Restored %d persistent view handlers.", restored)


bot = ServerBot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    """Global slash-command error handler."""
    from services.embed_service import error_embed

    if isinstance(error, discord.app_commands.CommandOnCooldown):
        em = error_embed("Cooldown", f"Try again in **{error.retry_after:.1f}s**.")
        await interaction.response.send_message(embed=em, ephemeral=True)
    elif isinstance(error, discord.app_commands.MissingPermissions):
        em = error_embed("Missing Permissions", "You lack the required permissions.")
        await interaction.response.send_message(embed=em, ephemeral=True)
    elif isinstance(error, discord.app_commands.CheckFailure):
        em = error_embed("Check Failed", str(error) or "You cannot use this command.")
        await interaction.response.send_message(embed=em, ephemeral=True)
    else:
        log.exception("Unhandled app-command error: %s", error)
        em = error_embed("Error", "An unexpected error occurred. Please try again later.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=em, ephemeral=True)
            else:
                await interaction.response.send_message(embed=em, ephemeral=True)
        except discord.HTTPException:
            pass


async def _start_health_server(host: str = "0.0.0.0", port: int | None = None) -> web.AppRunner:
    """Minimal lightweight HTTP health/keep-alive server for Render Web Service."""
    if port is None:
        port = int(os.environ.get("PORT", 10000))

    app = web.Application()

    async def _health_check(request: web.Request) -> web.Response:
        return web.Response(text="Damu Server Builder is alive")

    app.router.add_get("/", _health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("Keep-alive HTTP server listening on %s:%d", host, port)
    return runner


async def main() -> None:
    runner: web.AppRunner | None = None
    try:
        runner = await _start_health_server()
    except Exception as exc:
        log.warning("Could not start keep-alive HTTP server: %s", exc)

    try:
        async with bot:
            await asyncio.sleep(3)  # small delay before login
            await bot.start(config.DISCORD_TOKEN)
    finally:
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
