"""Regressions for the code and symptoms observed on Wispbyte."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import discord
import pytest
from discord.ext import commands
from core.discord_api.guard import api_guard
from core.interaction import safe_defer, InteractionResultReason
from engines.guild.channel_engine import ChannelEngine
from tests.test_security import FakeInteraction


@pytest.mark.asyncio
async def test_lock_and_unlock_acknowledge_once_in_both_response_states():
    from cogs.moderation import ModerationCog
    api_guard.reset()
    for command in (ModerationCog.lock, ModerationCog.unlock):
        for deferred in (False, True):
            interaction = FakeInteraction()
            if deferred:
                interaction.response.type = discord.InteractionResponseType.deferred_channel_message
            channel = Mock(spec=discord.TextChannel)
            channel.overwrites_for.return_value = discord.PermissionOverwrite(attach_files=False)
            channel.set_permissions = AsyncMock()
            await command.callback(ModerationCog(None), interaction, channel)
            interaction.response.send_message.assert_not_awaited()
            interaction.edit_original_response.assert_awaited_once()
            assert interaction.response.defer.await_count == int(not deferred)
            assert channel.set_permissions.await_args.kwargs['overwrite'].attach_files is False


@pytest.mark.asyncio
async def test_remote_already_acknowledged_defer_finishes_original_without_second_ack():
    from cogs.moderation import ModerationCog
    api_guard.reset()
    interaction = FakeInteraction()
    interaction.response.defer.side_effect = discord.HTTPException(
        SimpleNamespace(status=400, reason='Bad Request'), {'code': 40060, 'message': 'Already acknowledged'})
    channel = Mock(spec=discord.TextChannel)
    channel.overwrites_for.return_value = discord.PermissionOverwrite()
    channel.set_permissions = AsyncMock()
    await ModerationCog.lock.callback(ModerationCog(None), interaction, channel)
    interaction.response.send_message.assert_not_awaited()
    interaction.edit_original_response.assert_awaited_once()
    channel.set_permissions.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_manager_category_id_is_honored():
    guild = Mock(spec=discord.Guild)
    guild.me = SimpleNamespace(guild_permissions=discord.Permissions(manage_channels=True))
    category = Mock(spec=discord.CategoryChannel)
    guild.get_channel.return_value = category
    guild.create_text_channel = AsyncMock()
    await ChannelEngine().create_channel(guild, {'name': 'review', 'category_id': 123})
    guild.get_channel.assert_called_once_with(123)
    assert guild.create_text_channel.await_args.kwargs['category'] is category


@pytest.mark.asyncio
async def test_all_existing_and_security_commands_register_together():
    from tests.test_cogs import EXPECTED_COGS
    bot = commands.Bot(command_prefix='!', intents=discord.Intents.none())
    await bot._async_setup_hook()
    try:
        for name in EXPECTED_COGS:
            await bot.load_extension('cogs.' + name)
        old = {item.qualified_name for item in bot.tree.walk_commands()}
        assert len(bot.tree.get_commands()) == 61
        await bot.load_extension('cogs.security')
        await bot.load_extension('cogs.butler')
        new = {item.qualified_name for item in bot.tree.walk_commands()}
        assert old <= new
        for name in ('security', 'quarantine_setup', 'sudo_ban', 'quarantine_release', 'create_channel', 'help', 'diagnostics', 'sync_commands', 'bot_profile'):
            assert bot.tree.get_command(name) is not None
        for command in bot.tree.get_commands():
            command.to_dict(bot.tree)
        assert len(bot.tree.get_commands()) == 72
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_channel_preview_rechecks_administrator_before_engine_executes():
    from unittest.mock import patch
    from cogs.server_manager import ChangePreviewView
    from core.models import BuildPlan
    api_guard.reset()
    interaction = FakeInteraction()
    interaction.user.guild_permissions = discord.Permissions.none()
    view = ChangePreviewView(interaction.guild, interaction.user.id,
                             BuildPlan(guild_id=10, requester_id=1, operation='Create Channel'))
    with patch('cogs.server_manager.engine.execute', new_callable=AsyncMock) as execute:
        await view.apply.callback(interaction)
        execute.assert_not_awaited()
    view.stop()
