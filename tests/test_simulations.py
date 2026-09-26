"""Runtime simulations covering production failure and recovery scenarios (Scenarios A-F)."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.ticket_system import TicketSystem
from core.diagnostics import get_diagnostic_status
from core.discord_api.guard import api_guard
from core.discord_api.state import APIState
from core.health_server import health_app
from core.interaction import InteractionResultReason, safe_defer, safe_send
from core.startup.manager import StartupManager
from core.startup.state import StartupState
from engines.channel_engine import ChannelEngine


@pytest.fixture(autouse=True)
def reset_state():
    api_guard.reset()
    StartupManager._instance = None
    yield
    api_guard.reset()
    StartupManager._instance = None


def make_sim_bot():
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_closed.return_value = False
    bot.tree = MagicMock()
    bot.tree.add_command = MagicMock()
    bot.tree.remove_command = MagicMock()
    bot.add_view = MagicMock()
    return bot


def make_sim_interaction(guild_id=88888, user_id=99999):
    interaction = MagicMock(spec=discord.Interaction)
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = "SimGuild"
    guild.owner = None
    guild.me = MagicMock()
    guild.me.guild_permissions = discord.Permissions(
        manage_channels=True,
        send_messages=True,
        manage_messages=True,
        attach_files=True,
        embed_links=True,
    )
    guild.default_role = MagicMock(spec=discord.Role)

    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.name = "simuser"
    user.mention = f"<@{user_id}>"
    user.roles = []
    user.display_avatar = MagicMock()
    user.display_avatar.url = "http://example.com/avatar.png"

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 77777
    channel.send = AsyncMock()

    interaction.guild = guild
    interaction.user = user
    interaction.channel = channel
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    return interaction


# ── SCENARIO A: Bot READY, Discord returns Cloudflare 1015 ───────────────────
def test_scenario_a_cloudflare_1015_during_ready():
    bot = make_sim_bot()
    sm = StartupManager(bot=bot, token="TOKEN")
    sm._set_state(StartupState.READY)

    # Discord REST responds with Cloudflare 1015
    cf_html = "<html><head><title>Error 1015 Ray ID: 8e3b1234</title></head><body>You are being rate limited</body></html>"
    api_guard.record_failure(status=429, body=cf_html)

    # Verify process health endpoint: ALWAYS 200 while process alive
    client = health_app.test_client()
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.get_json() == {"status": "ok", "process": "alive"}

    # Verify readiness endpoint: 503 because API is blocked
    ready_resp = client.get("/ready")
    assert ready_resp.status_code == 503
    ready_data = ready_resp.get_json()
    assert ready_data["status"] == "not_ready"
    assert ready_data["api_state"] == "CLOUDFLARE_BLOCKED"

    # API state is guarded
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED
    assert api_guard.provider == "cloudflare"
    assert api_guard.is_cloudflare is True

    # Check that can_execute is false (prevents retry storm)
    allowed, state, retry_at = api_guard.can_execute()
    assert allowed is False
    assert state == APIState.CLOUDFLARE_BLOCKED


# ── SCENARIO B: Discord recovery ──────────────────────────────────────────────
def test_scenario_b_discord_recovery():
    bot = make_sim_bot()
    sm = StartupManager(bot=bot, token="TOKEN")
    sm._set_state(StartupState.READY)

    # Put in blocked state
    api_guard.record_failure(status=429, body="Error 1015", headers={"retry-after": "60"})
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED

    # Artificially expire the retry deadline
    api_guard._retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    # First check transitions to RECOVERING to allow controlled request
    allowed, state, _ = api_guard.can_execute()
    assert allowed is True
    assert state == APIState.RECOVERING

    # Probe request succeeds
    api_guard.record_success()
    assert api_guard.state == APIState.AVAILABLE

    # Readiness endpoint now returns 200 OK
    client = health_app.test_client()
    ready_resp = client.get("/ready")
    assert ready_resp.status_code == 200
    ready_data = ready_resp.get_json()
    assert ready_data["status"] == "ready"
    assert ready_data["api_state"] == "AVAILABLE"


# ── SCENARIO C: Ticket button during API block ─────────────────────────────────
@pytest.mark.asyncio
async def test_scenario_c_ticket_button_during_api_block():
    bot = make_sim_bot()
    cog = TicketSystem(bot)
    cog.config_manager._client_available = False
    cog.config_manager.col = None

    interaction = make_sim_interaction()

    # Pre-configure guild
    await cog.config_manager.save_guild(
        interaction.guild.id,
        {
            "ticket_category_id": 111,
            "support_role_id": 222,
            "mod_role_id": 333,
            "ticket_counter": 0,
        },
    )

    # API is blocked by Cloudflare 1015
    api_guard.record_failure(status=429, body="Error 1015")
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED

    with patch("cogs.ticket_system.ChannelEngine.create_text_channel", new_callable=AsyncMock) as mock_create:
        await cog.create_ticket(interaction, "Tech Support")

        # Must NOT attempt channel creation as fallback!
        mock_create.assert_not_awaited()

    # Interaction response deferral should have returned failure cleanly
    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["ticket_counter"] == 0  # No fake counter increment
    assert len(config.get("open_tickets", {})) == 0  # No orphan ticket


# ── SCENARIO D: Ticket button after API recovery ───────────────────────────────
@pytest.mark.asyncio
async def test_scenario_d_ticket_button_after_api_recovery():
    bot = make_sim_bot()
    cog = TicketSystem(bot)
    cog.config_manager._client_available = False
    cog.config_manager.col = None

    interaction = make_sim_interaction()

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction.guild.get_channel.return_value = category
    support_role = MagicMock(spec=discord.Role, id=222)
    support_role.mention = "@support"
    interaction.guild.get_role.return_value = support_role

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {
            "ticket_category_id": 111,
            "support_role_id": 222,
            "mod_role_id": 333,
            "ticket_counter": 0,
        },
    )

    # API is available
    api_guard.record_success()
    assert api_guard.state == APIState.AVAILABLE

    fake_ticket_channel = MagicMock(spec=discord.TextChannel, id=55555, name="ticket-0001-simuser")
    fake_ticket_channel.mention = "<#55555>"
    fake_ticket_channel.jump_url = "http://discord.com"
    fake_msg = MagicMock(spec=discord.Message, id=1001)
    fake_ticket_channel.send = AsyncMock(return_value=fake_msg)

    with patch(
        "cogs.ticket_system.ChannelEngine.create_text_channel",
        new_callable=AsyncMock,
        return_value=fake_ticket_channel,
    ):
        await cog.create_ticket(interaction, "Tech Support")

    # Ticket created successfully
    fake_ticket_channel.send.assert_awaited_once()
    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["ticket_counter"] == 1
    assert config["open_tickets"][str(interaction.user.id)] == 55555


# ── SCENARIO E: /setup_tickets during API block ────────────────────────────────
@pytest.mark.asyncio
async def test_scenario_e_setup_tickets_during_api_block():
    bot = make_sim_bot()
    cog = TicketSystem(bot)
    interaction = make_sim_interaction()

    # Block API
    api_guard.record_failure(status=429, body="Error 1015")
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    support_role = MagicMock(spec=discord.Role, id=222)
    mod_role = MagicMock(spec=discord.Role, id=333)
    log_channel = MagicMock(spec=discord.TextChannel, id=444)

    # Running /setup_tickets should exit gracefully with error message, no traceback
    await cog.setup_tickets.callback(
        cog,
        interaction=interaction,
        title="Tickets",
        description="Help",
        support_role=support_role,
        mod_role=mod_role,
        log_channel=log_channel,
        ticket_category=category,
    )

    # Panel message was NOT sent to channel
    interaction.channel.send.assert_not_awaited()


# ── SCENARIO F: /setup_tickets after recovery ──────────────────────────────────
@pytest.mark.asyncio
async def test_scenario_f_setup_tickets_after_recovery():
    bot = make_sim_bot()
    cog = TicketSystem(bot)
    cog.config_manager._client_available = False
    cog.config_manager.col = None
    interaction = make_sim_interaction()

    # Recovered API
    api_guard.record_success()
    assert api_guard.state == APIState.AVAILABLE

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    support_role = MagicMock(spec=discord.Role, id=222)
    mod_role = MagicMock(spec=discord.Role, id=333)
    log_channel = MagicMock(spec=discord.TextChannel, id=444)

    mock_panel_msg = MagicMock(spec=discord.Message, id=99001)
    interaction.channel.send = AsyncMock(return_value=mock_panel_msg)

    await cog.setup_tickets.callback(
        cog,
        interaction=interaction,
        title="Tickets",
        description="Help",
        support_role=support_role,
        mod_role=mod_role,
        log_channel=log_channel,
        ticket_category=category,
    )

    # Panel message sent to channel
    interaction.channel.send.assert_awaited_once()
    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["support_role_id"] == 222
    assert config["ticket_category_id"] == 111
