"""Entry point — initialises the bot, loads cogs, and starts the event loop."""

import asyncio
import datetime
import logging
import os
import pathlib
import sys
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask

import config
from utils.logger import setup_logging

# ── Keep-alive server for Render free tier ───────────────────────────────
_keep_alive_app = Flask(__name__)


@_keep_alive_app.route("/")
@_keep_alive_app.route("/health")
def _health_check():
    return "Bot is alive!", 200


def _run_keep_alive():
    port = int(os.environ.get("PORT", 8080))
    _keep_alive_app.run(host="0.0.0.0", port=port, use_reloader=False)


Thread(target=_run_keep_alive, daemon=True).start()
# ─────────────────────────────────────────────────────────────────────────

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

    async def setup_hook(self) -> None:
        """Load all cogs dynamically from the cogs/ directory."""
        cog_dir = pathlib.Path("cogs")
        for cog_file in cog_dir.glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
            ext = f"cogs.{cog_file.stem}"
            try:
                await self.load_extension(ext)
                log.info("Loaded cog: %s", ext)
            except Exception as exc:
                log.error("Failed to load cog %s: %s", ext, exc)

        # Sync application commands globally
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands globally.", len(synced))
        except Exception as exc:
            log.error("Failed to sync application commands: %s", exc)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)  # type: ignore[union-attr]
        log.info("Guilds: %d | Latency: %.0fms", len(self.guilds), self.latency * 1000)


bot = ServerBot()


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    """Centralized slash-command error handler for DAMU Core Engine."""
    from core.errors import format_user_error
    from core.interaction import safe_send
    from engines.health.health_engine import health_engine
    from services.embed_service import error_embed

    # Extract original underlying exception if wrapped in CommandInvokeError
    orig = getattr(error, "original", error)
    health_engine.record_error(f"{type(orig).__name__}: {orig}")

    if isinstance(error, discord.app_commands.CommandOnCooldown):
        em = error_embed("Cooldown", f"Please wait **{error.retry_after:.1f}s** before reusing this command.")
        await safe_send(interaction, embed=em, ephemeral=True)
    elif isinstance(error, discord.app_commands.MissingPermissions):
        perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
        em = error_embed("Missing Permissions", f"You lack the required permissions: {perms}")
        await safe_send(interaction, embed=em, ephemeral=True)
    elif isinstance(error, discord.app_commands.CheckFailure):
        em = error_embed("Check Failed", str(error) or "You cannot use this command.")
        await safe_send(interaction, embed=em, ephemeral=True)
    else:
        log.exception("App command error for %s: %s", getattr(interaction.command, "name", "unknown"), orig)
        cmd_name = getattr(interaction.command, "name", "action")
        em = format_user_error(orig, operation_name=f"/{cmd_name}")
        await safe_send(interaction, embed=em, ephemeral=True)


async def main() -> None:
    # ── Safe Diagnostics (No secret exposure) ────────────────────────────────
    raw_env_token = os.getenv("DISCORD_TOKEN")
    env_detected = "YES" if raw_env_token is not None else "NO"
    has_length = "YES" if bool(raw_env_token and len(raw_env_token.strip()) > 0) else "NO"

    log.info("DISCORD_TOKEN environment variable detected: %s", env_detected)
    log.info("token length detected: %s", has_length)

    # Normalize token before bot.start(): strip whitespace and matching quotes
    token = config.normalize_token(raw_env_token)

    # Validate token presence and check for common placeholder errors
    try:
        config.validate_discord_token(token)
    except RuntimeError as err:
        log.error("Startup validation failed: %s", err)
        sys.exit(1)

    async with bot:
        try:
            await bot.start(token)
        except (discord.errors.LoginFailure, discord.errors.HTTPException) as exc:
            if isinstance(exc, discord.errors.LoginFailure) or (
                isinstance(exc, discord.errors.HTTPException) and getattr(exc, "status", None) == 401
            ):
                log.error(
                    "Discord authentication failed (401). The configured Discord bot token was rejected by Discord. "
                    "Verify that DISCORD_TOKEN contains the current Bot Token for this exact Discord application."
                )
                sys.exit(1)
            raise


if __name__ == "__main__":
    asyncio.run(main())
