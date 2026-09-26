"""Tests for all 11 cogs, setup, commands, and view registration (Tests 41-45)."""

import importlib
import pathlib
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands
import pytest

from cogs.ticket_system import TicketControlView, TicketPanelView

EXPECTED_COGS = [
    "ai",
    "analytics",
    "automod",
    "dashboard",
    "leveling",
    "moderation",
    "server_builder",
    "server_manager",
    "ticket_system",
    "utility",
    "verification",
]


# ── Test 41: All cogs import ──────────────────────────────────────────────────
def test_all_cogs_import():
    for cog_name in EXPECTED_COGS:
        mod = importlib.import_module(f"cogs.{cog_name}")
        assert mod is not None, f"Failed to import cogs.{cog_name}"
        assert hasattr(mod, "setup"), f"Cog cogs.{cog_name} missing setup function"


# ── Test 42: All cogs setup ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_all_cogs_setup():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

    for cog_name in EXPECTED_COGS:
        ext = f"cogs.{cog_name}"
        await bot.load_extension(ext)

    loaded = [c.lower() for c in bot.cogs.keys()]
    assert len(loaded) >= len(EXPECTED_COGS)


# ── Test 43: Expected commands registered ─────────────────────────────────────
@pytest.mark.asyncio
async def test_expected_commands_registered():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

    for cog_name in EXPECTED_COGS:
        await bot.load_extension(f"cogs.{cog_name}")

    commands_list = bot.tree.get_commands()
    assert len(commands_list) == 61

    command_names = {c.name for c in commands_list}

    # Verify key commands from critical subsystems exist
    assert "setup_tickets" in command_names
    assert "ticket_blacklist" in command_names
    assert "server_manager" in command_names
    assert "server_analyze" in command_names
    assert "setup_server" in command_names
    assert "kick" in command_names
    assert "ban" in command_names
    assert "setupverification" in command_names
    assert "ping" in command_names


# ── Test 44: Persistent views load ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_persistent_views_load():
    panel_view = TicketPanelView()
    assert panel_view.is_persistent() is True
    assert len(panel_view.children) == 3

    custom_ids = {getattr(btn, "custom_id", None) for btn in panel_view.children}
    assert "ticket_panel_tech" in custom_ids
    assert "ticket_panel_server" in custom_ids
    assert "ticket_panel_mod" in custom_ids

    control_view = TicketControlView()
    assert control_view.is_persistent() is True
    control_ids = {getattr(btn, "custom_id", None) for btn in control_view.children}
    assert "ticket_claim" in control_ids
    assert "ticket_close" in control_ids


# ── Test 45: Unrelated cog remains available if one feature fails ─────────────
@pytest.mark.asyncio
async def test_unrelated_cogs_resilient_to_feature_failure():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

    # Load all cogs
    for cog_name in EXPECTED_COGS:
        await bot.load_extension(f"cogs.{cog_name}")

    # Unload ticket_system simulating isolated failure
    await bot.unload_extension("cogs.ticket_system")

    # Moderation, server_builder, utility, etc. must remain registered and available
    assert "Moderation" in bot.cogs
    assert "Server Builder" in bot.cogs
    assert "Utility" in bot.cogs
    assert "Server Manager" in bot.cogs

