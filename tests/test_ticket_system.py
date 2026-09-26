"""Tests for Ticket System with transactional rollback and resilience (Tests 29-40)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.ticket_system import ConfigManager, TicketSystem
from core.discord_api.guard import api_guard
from core.discord_api.state import APIState


_id_counter = 1000


@pytest.fixture(autouse=True)
def reset_guard():
    api_guard.reset()
    yield
    api_guard.reset()


def make_mock_bot():
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.tree.add_command = MagicMock()
    bot.tree.remove_command = MagicMock()
    bot.add_view = MagicMock()
    return bot


def make_test_cog():
    bot = make_mock_bot()
    cog = TicketSystem(bot)
    cog.config_manager._client_available = False
    cog.config_manager.col = None
    cog.config_manager._cache.clear()
    return cog


def make_mock_interaction(guild_id=None, user_id=None, user_name="testuser"):
    global _id_counter
    _id_counter += 1
    gid = guild_id if guild_id is not None else 10000 + _id_counter
    uid = user_id if user_id is not None else 20000 + _id_counter

    interaction = MagicMock(spec=discord.Interaction)
    guild = MagicMock(spec=discord.Guild)
    guild.id = gid
    guild.name = "TestGuild"
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
    user.name = user_name
    user.mention = f"<@{user_id}>"
    user.roles = []
    user.display_avatar = MagicMock()
    user.display_avatar.url = "http://example.com/avatar.png"

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 55555
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


# ── Test 29: Ticket setup success ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ticket_setup_success():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    category = MagicMock(spec=discord.CategoryChannel)
    category.id = 111
    support_role = MagicMock(spec=discord.Role)
    support_role.id = 222
    mod_role = MagicMock(spec=discord.Role)
    mod_role.id = 333
    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.id = 444

    await cog.setup_tickets.callback(
        cog,
        interaction=interaction,
        title="Support Tickets",
        description="Click below to open a ticket",
        support_role=support_role,
        mod_role=mod_role,
        log_channel=log_channel,
        ticket_category=category,
    )

    interaction.channel.send.assert_awaited_once()
    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["support_role_id"] == 222
    assert config["mod_role_id"] == 333
    assert config["ticket_category_id"] == 111


# ── Test 30: Ticket setup while API blocked ───────────────────────────────────
@pytest.mark.asyncio
async def test_ticket_setup_while_api_blocked():
    api_guard.record_failure(status=429, body="Error 1015")
    assert api_guard.state == APIState.CLOUDFLARE_BLOCKED

    cog = make_test_cog()
    interaction = make_mock_interaction()

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    support_role = MagicMock(spec=discord.Role, id=222)
    mod_role = MagicMock(spec=discord.Role, id=333)
    log_channel = MagicMock(spec=discord.TextChannel, id=444)

    await cog.setup_tickets.callback(
        cog,
        interaction=interaction,
        title="Support Tickets",
        description="Click below",
        support_role=support_role,
        mod_role=mod_role,
        log_channel=log_channel,
        ticket_category=category,
    )

    # Should NOT attempt to send the ticket panel embed to Discord channel
    interaction.channel.send.assert_not_awaited()


# ── Test 31: Ticket button while API blocked ──────────────────────────────────
@pytest.mark.asyncio
async def test_ticket_button_while_api_blocked():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    # Preload config
    await cog.config_manager.save_guild(
        interaction.guild.id,
        {
            "ticket_category_id": 111,
            "support_role_id": 222,
            "mod_role_id": 333,
        },
    )

    # Block API
    api_guard.record_failure(status=429, body="Error 1015")

    with patch("cogs.ticket_system.ChannelEngine.create_text_channel", new_callable=AsyncMock) as mock_create:
        await cog.create_ticket(interaction, "Tech Support")
        # CRITICAL: Channel creation MUST NOT be called as fallback!
        mock_create.assert_not_awaited()


# ── Test 32: Ticket button after recovery ─────────────────────────────────────
@pytest.mark.asyncio
async def test_ticket_button_after_recovery():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction.guild.get_channel.return_value = category
    support_role = MagicMock(spec=discord.Role, id=222)
    support_role.mention = "@support"
    mod_role = MagicMock(spec=discord.Role, id=333)
    mod_role.mention = "@mod"
    interaction.guild.get_role.side_effect = lambda rid: support_role if rid == 222 else mod_role

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {
            "ticket_category_id": 111,
            "support_role_id": 222,
            "mod_role_id": 333,
            "ticket_counter": 0,
        },
    )

    fake_ticket_channel = MagicMock(spec=discord.TextChannel)
    fake_ticket_channel.id = 99999
    fake_ticket_channel.name = "ticket-0001-testuser"
    fake_ticket_channel.mention = "<#99999>"
    fake_ticket_channel.jump_url = "http://discord.com/jump"
    mock_sent_msg = MagicMock(spec=discord.Message)
    mock_sent_msg.id = 123456
    fake_ticket_channel.send = AsyncMock(return_value=mock_sent_msg)

    with patch(
        "cogs.ticket_system.ChannelEngine.create_text_channel",
        new_callable=AsyncMock,
        return_value=fake_ticket_channel,
    ):
        await cog.create_ticket(interaction, "Tech Support")

    fake_ticket_channel.send.assert_awaited_once()
    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["ticket_counter"] == 1
    assert config["open_tickets"][str(interaction.user.id)] == 99999


# ── Test 33: Ticket creation rollback ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_ticket_creation_rollback_on_message_failure():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction.guild.get_channel.return_value = category

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {
            "ticket_category_id": 111,
            "ticket_counter": 5,
        },
    )

    fake_ticket_channel = MagicMock(spec=discord.TextChannel)
    fake_ticket_channel.id = 77777
    fake_ticket_channel.name = "ticket-0006-testuser"
    fake_ticket_channel.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "Discord Error"))

    with patch(
        "cogs.ticket_system.ChannelEngine.create_text_channel",
        new_callable=AsyncMock,
        return_value=fake_ticket_channel,
    ), patch(
        "cogs.ticket_system.ChannelEngine.delete_channel_safe",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        await cog.create_ticket(interaction, "Server Support")

        mock_delete.assert_awaited_once_with(
            fake_ticket_channel,
            reason="Ticket transaction rollback due to initialization error",
        )

    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert str(interaction.user.id) not in config.get("open_tickets", {})


# ── Test 34: MongoDB unavailable (safe cache fallback) ────────────────────────
@pytest.mark.asyncio
async def test_mongodb_unavailable_cache_fallback():
    cm = ConfigManager()
    cm._client_available = False
    cm.col = None

    saved = await cm.save_guild(12345, {"ticket_counter": 10, "open_tickets": {}})
    assert saved is True

    data = await cm.get_guild(12345)
    assert data["ticket_counter"] == 10


# ── Test 35: Discord unavailable + MongoDB available ──────────────────────────
@pytest.mark.asyncio
async def test_discord_unavailable_mongodb_available():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {"ticket_category_id": 111, "ticket_counter": 1},
    )

    resp = MagicMock(status=429, reason="Too Many Requests")
    http_429 = discord.HTTPException(response=resp, message="Rate limited")
    interaction.response.defer.side_effect = http_429

    with patch("cogs.ticket_system.ChannelEngine.create_text_channel", new_callable=AsyncMock) as mock_create:
        await cog.create_ticket(interaction, "Mod Support")
        mock_create.assert_not_awaited()

    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["ticket_counter"] == 1


# ── Test 36: Discord available + MongoDB unavailable ──────────────────────────
@pytest.mark.asyncio
async def test_discord_available_mongodb_unavailable():
    cog = make_test_cog()
    cog.config_manager._client_available = False
    cog.config_manager.col = None

    interaction = make_mock_interaction()
    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction.guild.get_channel.return_value = category

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {"ticket_category_id": 111, "ticket_counter": 0},
    )

    fake_ticket_channel = MagicMock(spec=discord.TextChannel, id=888, name="ticket-0001-testuser")
    fake_ticket_channel.mention = "<#888>"
    fake_ticket_channel.jump_url = "http://discord.com"
    fake_msg = MagicMock(spec=discord.Message, id=1111)
    fake_ticket_channel.send = AsyncMock(return_value=fake_msg)

    with patch(
        "cogs.ticket_system.ChannelEngine.create_text_channel",
        new_callable=AsyncMock,
        return_value=fake_ticket_channel,
    ):
        await cog.create_ticket(interaction, "Tech Support")

    fake_ticket_channel.send.assert_awaited_once()
    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert config["ticket_counter"] == 1


# ── Test 37: Duplicate ticket prevention ──────────────────────────────────────
@pytest.mark.asyncio
async def test_duplicate_ticket_prevention():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    existing_channel = MagicMock(spec=discord.TextChannel, id=777)
    existing_channel.mention = "<#777>"
    interaction.guild.get_channel.return_value = existing_channel

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {
            "ticket_category_id": 111,
            "open_tickets": {str(interaction.user.id): 777},
        },
    )

    with patch("cogs.ticket_system.ChannelEngine.create_text_channel", new_callable=AsyncMock) as mock_create:
        await cog.create_ticket(interaction, "Tech Support")
        mock_create.assert_not_awaited()

    interaction.response.send_message.assert_awaited_once()


# ── Test 38: Ticket counter consistency ───────────────────────────────────────
@pytest.mark.asyncio
async def test_ticket_counter_consistency():
    cog = make_test_cog()
    interaction1 = make_mock_interaction(guild_id=99999, user_id=101, user_name="user1")
    interaction2 = make_mock_interaction(guild_id=99999, user_id=102, user_name="user2")
    interaction2.guild = interaction1.guild

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction1.guild.get_channel.return_value = category
    interaction2.guild.get_channel.return_value = category

    await cog.config_manager.save_guild(
        interaction1.guild.id,
        {"ticket_category_id": 111, "ticket_counter": 10},
    )

    created_names = []

    async def fake_create_channel(guild, name, **kwargs):
        created_names.append(name)
        ch = MagicMock(spec=discord.TextChannel, id=len(created_names), name=name)
        ch.mention = f"<#{len(created_names)}>"
        ch.jump_url = "http://example.com"
        fake_msg = MagicMock(spec=discord.Message, id=100 + len(created_names))
        ch.send = AsyncMock(return_value=fake_msg)
        return ch

    with patch("cogs.ticket_system.ChannelEngine.create_text_channel", side_effect=fake_create_channel):
        await cog.create_ticket(interaction1, "Tech Support")
        await cog.create_ticket(interaction2, "Server Support")

    assert created_names == ["ticket-0011-user1", "ticket-0012-user2"]
    config = await cog.config_manager.get_guild(interaction1.guild.id)
    assert config["ticket_counter"] == 12


# ── Test 39: No orphan channel on rollback ────────────────────────────────────
@pytest.mark.asyncio
async def test_no_orphan_channel_on_rollback():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction.guild.get_channel.return_value = category

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {"ticket_category_id": 111, "ticket_counter": 0},
    )

    orphan_channel = MagicMock(spec=discord.TextChannel, id=999, name="ticket-0001-testuser")
    orphan_channel.send = AsyncMock(side_effect=Exception("Failed to send message"))

    deleted_channels = []

    async def fake_delete(channel, reason=""):
        deleted_channels.append(channel.id)
        return True

    with patch(
        "cogs.ticket_system.ChannelEngine.create_text_channel",
        new_callable=AsyncMock,
        return_value=orphan_channel,
    ), patch("cogs.ticket_system.ChannelEngine.delete_channel_safe", side_effect=fake_delete):
        await cog.create_ticket(interaction, "Tech Support")

    assert orphan_channel.id in deleted_channels


# ── Test 40: No orphan database state ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_orphan_database_state():
    cog = make_test_cog()
    interaction = make_mock_interaction()

    category = MagicMock(spec=discord.CategoryChannel, id=111)
    interaction.guild.get_channel.return_value = category

    await cog.config_manager.save_guild(
        interaction.guild.id,
        {"ticket_category_id": 111, "ticket_counter": 3, "open_tickets": {}},
    )

    orphan_channel = MagicMock(spec=discord.TextChannel, id=999, name="ticket-0004-testuser")
    orphan_channel.send = AsyncMock(side_effect=Exception("Send message failed"))

    with patch(
        "cogs.ticket_system.ChannelEngine.create_text_channel",
        new_callable=AsyncMock,
        return_value=orphan_channel,
    ), patch(
        "cogs.ticket_system.ChannelEngine.delete_channel_safe",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await cog.create_ticket(interaction, "Tech Support")

    config = await cog.config_manager.get_guild(interaction.guild.id)
    assert str(interaction.user.id) not in config["open_tickets"]
