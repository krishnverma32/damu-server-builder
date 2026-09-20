"""Tests for diff engine and conflict detection."""
from __future__ import annotations

from unittest.mock import MagicMock
import discord
from builder.diff import ResourceChange, ServerDiffResult, calculate_server_diff
from builder.models import ServerConfig


def test_server_diff_result_totals():
    res = ServerDiffResult()
    res.roles_create.append(ResourceChange("create", "role", "Admin"))
    res.categories_create.append(ResourceChange("create", "category", "Staff"))
    res.channels_create.append(ResourceChange("create", "channel", "mod-chat"))
    res.channels_update.append(ResourceChange("update", "channel", "general", "slowmode changed"))
    res.roles_delete.append(ResourceChange("delete", "role", "OldRole"))

    assert res.total_creations() == 3
    assert res.total_updates() == 1
    assert res.total_deletions() == 1

    formatted = res.format_diff_text()
    assert "+ @Admin" in formatted
    assert "+ Staff" in formatted
    assert "+ #mod-chat" in formatted
    assert "- @OldRole" in formatted


def test_calculate_server_diff_with_mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.name = "Mock Guild"
    guild.roles = []
    guild.categories = []
    guild.channels = []
    guild.features = ["COMMUNITY"]

    me = MagicMock(spec=discord.Member)
    me.guild_permissions = discord.Permissions.all()
    me.top_role = MagicMock(spec=discord.Role)
    me.top_role.position = 100
    guild.me = me

    config = ServerConfig.from_dict({
        "server_name": "Mock Guild",
        "roles": [{"name": "VIP", "color": "gold"}],
        "categories": [
            {
                "name": "Community",
                "channels": [{"name": "chat", "type": "text"}],
            }
        ],
    })

    diff = calculate_server_diff(guild, config)
    assert len(diff.roles_create) == 1
    assert diff.roles_create[0].name == "VIP"
    assert len(diff.categories_create) == 1
    assert len(diff.channels_create) == 1
    assert len(diff.conflicts) == 0
