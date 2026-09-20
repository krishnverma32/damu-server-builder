"""End-to-end integration tests for critical Discord builder flows.

Tests:
1. build_server creating roles, categories, text, voice, stage, forum, announcement channels with overwrites.
2. Category inheritance when channel overwrites are omitted vs explicit overwrites.
3. Role and member overwrites mapping Allow / Deny / Inherit correctly.
4. Channel and category cloning preserving settings and overwrites.
5. Snapshot extraction and restore schema validation.
6. Rollback confirmation view and build repository rollback tracking.
7. Persistent ViewRegistry registration and restoration across restarts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
import discord

from builder.engine import build_server
from builder.cloning import clone_category_resource, clone_channel_resource
from builder.snapshot import take_guild_snapshot, validate_snapshot_data
from builder.permissions import tri_state_to_overwrite, overwrite_to_tri_state
from builder.views import RollbackConfirmView
from services.database import Database
from services.view_registry import ViewRegistry
from services.repositories import BuildRepository


def _make_mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 999111222
    guild.name = "Original Guild"
    guild.bitrate_limit = 96000
    guild.features = ["COMMUNITY"]

    # Default role
    default_role = MagicMock(spec=discord.Role)
    default_role.id = 999111222
    default_role.name = "@everyone"
    default_role.is_default.return_value = True
    default_role.managed = False
    default_role.permissions = discord.Permissions(send_messages=True, view_channel=True)
    guild.default_role = default_role
    guild.roles = [default_role]

    # Bot member
    me = MagicMock(spec=discord.Member)
    me.id = 888777666
    me.guild_permissions = discord.Permissions.all()
    me.top_role = MagicMock(spec=discord.Role)
    me.top_role.position = 99
    guild.me = me

    # Member in guild
    member = MagicMock(spec=discord.Member)
    member.id = 123456789
    member.name = "TestUser"
    guild.get_member.return_value = member
    guild.members = [me, member]

    guild.categories = []
    guild.channels = []
    guild.text_channels = []
    guild.voice_channels = []
    guild.stage_channels = []
    guild.forums = []

    # Mock async factory methods
    async def mock_edit(**kwargs):
        if "name" in kwargs:
            guild.name = kwargs["name"]

    async def mock_create_role(**kwargs):
        r = MagicMock(spec=discord.Role)
        r.id = len(guild.roles) + 1000
        r.name = kwargs.get("name", "new-role")
        r.colour = kwargs.get("colour", discord.Colour.default())
        r.hoist = kwargs.get("hoist", False)
        r.mentionable = kwargs.get("mentionable", False)
        r.permissions = kwargs.get("permissions", discord.Permissions.none())
        r.is_default.return_value = False
        r.managed = False
        guild.roles.append(r)
        return r

    async def mock_create_category(**kwargs):
        cat = MagicMock(spec=discord.CategoryChannel)
        cat.id = len(guild.categories) + 2000
        cat.name = kwargs.get("name", "new-cat")
        cat.overwrites = kwargs.get("overwrites", {})
        cat.channels = []
        cat.guild = guild
        guild.categories.append(cat)
        guild.channels.append(cat)
        return cat

    async def mock_create_text_channel(**kwargs):
        ch = MagicMock(spec=discord.TextChannel)
        ch.id = len(guild.channels) + 3000
        ch.name = kwargs.get("name", "new-text")
        ch.category = kwargs.get("category")
        ch.topic = kwargs.get("topic", "")
        ch.slowmode_delay = kwargs.get("slowmode_delay", 0)
        ch.nsfw = kwargs.get("nsfw", False)
        ch._news = kwargs.get("news", False)
        ch.is_news.return_value = ch._news
        ch.overwrites = kwargs.get("overwrites", {})
        ch.guild = guild
        if ch.category:
            ch.category.channels.append(ch)
        guild.text_channels.append(ch)
        guild.channels.append(ch)
        return ch

    async def mock_create_voice_channel(**kwargs):
        ch = MagicMock(spec=discord.VoiceChannel)
        ch.id = len(guild.channels) + 4000
        ch.name = kwargs.get("name", "new-voice")
        ch.category = kwargs.get("category")
        ch.bitrate = kwargs.get("bitrate", 64000)
        ch.user_limit = kwargs.get("user_limit", 0)
        ch.overwrites = kwargs.get("overwrites", {})
        ch.guild = guild
        if ch.category:
            ch.category.channels.append(ch)
        guild.voice_channels.append(ch)
        guild.channels.append(ch)
        return ch

    async def mock_create_stage_channel(**kwargs):
        ch = MagicMock(spec=discord.StageChannel)
        ch.id = len(guild.channels) + 5000
        ch.name = kwargs.get("name", "new-stage")
        ch.category = kwargs.get("category")
        ch.topic = kwargs.get("topic", "")
        ch.bitrate = kwargs.get("bitrate", 64000)
        ch.user_limit = kwargs.get("user_limit", 0)
        ch.overwrites = kwargs.get("overwrites", {})
        ch.guild = guild
        if ch.category:
            ch.category.channels.append(ch)
        guild.stage_channels.append(ch)
        guild.channels.append(ch)
        return ch

    async def mock_create_forum(**kwargs):
        ch = MagicMock(spec=discord.ForumChannel)
        ch.id = len(guild.channels) + 6000
        ch.name = kwargs.get("name", "new-forum")
        ch.category = kwargs.get("category")
        ch.topic = kwargs.get("topic", "")
        ch.slowmode_delay = kwargs.get("slowmode_delay", 0)
        ch.nsfw = kwargs.get("nsfw", False)
        ch.default_thread_slowmode_delay = 0
        ch.default_auto_archive_duration = 1440
        ch.default_sort_order = None
        ch.default_layout = None
        ch.available_tags = []
        ch.overwrites = kwargs.get("overwrites", {})
        ch.guild = guild
        if ch.category:
            ch.category.channels.append(ch)
        guild.forums.append(ch)
        guild.channels.append(ch)
        return ch

    guild.edit = AsyncMock(side_effect=mock_edit)
    guild.create_role = AsyncMock(side_effect=mock_create_role)
    guild.create_category = AsyncMock(side_effect=mock_create_category)
    guild.create_text_channel = AsyncMock(side_effect=mock_create_text_channel)
    guild.create_voice_channel = AsyncMock(side_effect=mock_create_voice_channel)
    guild.create_stage_channel = AsyncMock(side_effect=mock_create_stage_channel)
    guild.create_forum = AsyncMock(side_effect=mock_create_forum)

    return guild


def test_build_server_all_channel_types_and_overwrites():
    """Verify build_server creates roles, categories, and text/voice/stage/forum channels with overwrites."""
    async def run():
        mock_guild = _make_mock_guild()
        schema = {
            "server_name": "Integration Test Guild",
            "roles": [
                {"name": "Admin", "color": "red", "permissions": ["administrator"]},
                {"name": "Moderator", "color": "blue", "permissions": ["manage_messages"]},
            ],
            "categories": [
                {
                    "name": "Community",
                    "permission_overwrites": [
                        {
                            "role": "@everyone",
                            "allow": ["view_channel"],
                            "deny": ["mention_everyone"],
                        }
                    ],
                    "channels": [
                        {
                            "name": "general",
                            "type": "text",
                            "topic": "General chat",
                        },
                        {
                            "name": "announcements",
                            "type": "announcement",
                            "permission_overwrites": [
                                {
                                    "role": "@everyone",
                                    "allow": ["view_channel"],
                                    "deny": ["send_messages"],
                                },
                                {
                                    "role": "Admin",
                                    "allow": ["send_messages"],
                                    "deny": [],
                                },
                            ],
                        },
                        {
                            "name": "Lounge",
                            "type": "voice",
                            "bitrate": 64000,
                            "user_limit": 10,
                        },
                        {
                            "name": "Town Hall",
                            "type": "stage",
                            "topic": "Community Discussions",
                        },
                        {
                            "name": "Feedback",
                            "type": "forum",
                            "topic": "Share ideas",
                        },
                    ],
                }
            ],
        }

        logs, role_map = await build_server(mock_guild, schema)

        # 1. Server name was updated
        assert mock_guild.name == "Integration Test Guild"

        # 2. Roles created
        assert "Admin" in role_map
        assert "Moderator" in role_map
        assert len(mock_guild.roles) == 3  # default + Admin + Moderator

        # 3. Categories created
        assert len(mock_guild.categories) == 1
        cat = mock_guild.categories[0]
        assert cat.name == "Community"
        assert mock_guild.default_role in cat.overwrites
        default_ow = cat.overwrites[mock_guild.default_role]
        allow, deny = default_ow.pair()
        assert allow.view_channel is True
        assert deny.mention_everyone is True

        # 4. Channels created
        assert len(mock_guild.text_channels) == 2  # general + announcements
        assert len(mock_guild.voice_channels) == 1  # Lounge
        assert len(mock_guild.stage_channels) == 1  # Town Hall
        assert len(mock_guild.forums) == 1  # Feedback

        # 5. Overwrites check
        announcements = [c for c in mock_guild.text_channels if c.name == "announcements"][0]
        admin_role = role_map["Admin"]
        assert admin_role in announcements.overwrites
        admin_ow = announcements.overwrites[admin_role]
        admin_allow, _ = admin_ow.pair()
        assert admin_allow.send_messages is True

    asyncio.run(run())


def test_clone_channel_and_category_preserves_settings():
    """Verify clone_channel_resource and clone_category_resource preserve all attributes."""
    async def run():
        mock_guild = _make_mock_guild()
        # Setup source channel
        src_text = MagicMock(spec=discord.TextChannel)
        src_text.guild = mock_guild
        src_text.name = "source-text"
        src_text.category = None
        src_text.topic = "Important Source Topic"
        src_text.slowmode_delay = 15
        src_text.nsfw = True
        src_text.is_news.return_value = True
        src_text.overwrites = {
            mock_guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False)
        }

        cloned = await clone_channel_resource(src_text, "cloned-text")
        assert cloned.name == "cloned-text"
        assert cloned.topic == "Important Source Topic"
        assert cloned.slowmode_delay == 15
        assert cloned.nsfw is True
        assert cloned.overwrites == src_text.overwrites

        # Setup source category
        src_cat = MagicMock(spec=discord.CategoryChannel)
        src_cat.guild = mock_guild
        src_cat.name = "Source Category"
        src_cat.position = 2
        src_cat.overwrites = src_text.overwrites
        src_cat.channels = [src_text]

        cloned_cat, cloned_channels = await clone_category_resource(src_cat, "Cloned Category")
        assert cloned_cat.name == "Cloned Category"
        assert cloned_cat.overwrites == src_cat.overwrites
        assert len(cloned_channels) == 1
        assert cloned_channels[0].name == "source-text"

    asyncio.run(run())


def test_allow_deny_inherit_three_state_mapping():
    """Verify three-state permission dictionary roundtrips with discord.PermissionOverwrite."""
    input_states = {
        "view_channel": True,
        "send_messages": False,
        "read_message_history": None,
    }

    ow = tri_state_to_overwrite(input_states)
    assert ow.view_channel is True
    assert ow.send_messages is False
    assert ow.read_message_history is None

    out_states = overwrite_to_tri_state(ow)
    assert out_states["view_channel"] is True
    assert out_states["send_messages"] is False
    assert out_states["read_message_history"] is None


def test_take_guild_snapshot_and_validate():
    """Verify take_guild_snapshot extracts valid schema data matching validate_snapshot_data."""
    async def run():
        mock_guild = _make_mock_guild()
        # Populate mock guild with roles and channels
        await mock_guild.create_role(name="VIP", colour=discord.Colour.gold())
        cat = await mock_guild.create_category(name="General Area")
        await mock_guild.create_text_channel(name="chat", category=cat, topic="General Chat")

        snapshot = take_guild_snapshot(mock_guild)
        assert "roles" in snapshot
        assert "categories" in snapshot
        assert any(r["name"] == "VIP" for r in snapshot["roles"])
        assert any(c["name"] == "General Area" for c in snapshot["categories"])

        # Must pass schema validation
        from builder.models import ServerConfig
        cfg = validate_snapshot_data(snapshot)
        assert isinstance(cfg, ServerConfig)
        assert cfg.to_dict()["server_name"] == mock_guild.name

    asyncio.run(run())


def test_rollback_confirmation_view_and_repository(tmp_path):
    """Verify RollbackConfirmView buttons work and BuildRepository tracks status."""
    async def run():
        db_file = tmp_path / "test_damu_rollback.db"
        db = Database(str(db_file))
        await db.create_tables()

        repo = BuildRepository(db)
        build_id = await repo.create_build(
            guild_id=111,
            user_id=42,
            template="community",
            schema_version="2.0",
            plan_dict={},
        )
        await repo.complete_build(build_id, status="completed", created_resources=[201, 202, 203])

        # Check view logic
        view = RollbackConfirmView(user_id=42)
        assert view.confirmed is None

        # Foreign user rejected
        foreign_interaction = MagicMock(spec=discord.Interaction)
        foreign_interaction.user = MagicMock(spec=discord.Member)
        foreign_interaction.user.id = 999
        foreign_interaction.user.guild_permissions = discord.Permissions(administrator=True)
        foreign_interaction.response.send_message = AsyncMock()

        allowed = await view.interaction_check(foreign_interaction)
        assert allowed is False
        foreign_interaction.response.send_message.assert_called_once()

        # Author confirmed
        author_interaction = MagicMock(spec=discord.Interaction)
        author_interaction.user = MagicMock(spec=discord.Member)
        author_interaction.user.id = 42
        author_interaction.user.guild_permissions = discord.Permissions(administrator=True)
        author_interaction.response.edit_message = AsyncMock()

        button = MagicMock(spec=discord.ui.Button)
        await view.confirm.callback(author_interaction)
        assert view.confirmed is True

        # Mark rolled back in repo
        await repo.record_rollback(build_id)
        record = await repo.get_build(build_id)
        assert record["status"] == "rolled_back"
        await db.close()

    asyncio.run(run())


def test_view_registry_registration_and_restoration(tmp_path):
    """Verify ViewRegistry registers ticket and verification views and restores them."""
    async def run():
        db_file = tmp_path / "test_views.db"
        db = Database(str(db_file))
        await db.create_tables()

        registry = ViewRegistry()
        registry.db = db
        mock_bot = MagicMock()
        mock_bot.add_view = MagicMock()

        # Register persistent views
        from cogs.verification import VerificationView
        from cogs.ticket_system import TicketPanelView, TicketControlView

        v_view = VerificationView()
        tp_view = TicketPanelView()
        tc_view = TicketControlView()

        await registry.register("verify_msg_1", v_view)
        await registry.register("ticket_panel_1", tp_view)
        await registry.register("ticket_ctrl_1", tc_view)

        # Simulate restart: fresh registry instance restoring views
        fresh_registry = ViewRegistry()
        fresh_registry.db = db
        restored_count = await fresh_registry.restore_all(mock_bot)

        # 3 view types restored
        assert restored_count == 3
        assert mock_bot.add_view.call_count == 3
        await db.close()

    asyncio.run(run())
