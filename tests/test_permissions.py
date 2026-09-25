"""Tests for Permission Engine and Dangerous Permissions."""

from __future__ import annotations

import discord
import pytest

from engines.guild.permission_engine import (
    DANGEROUS_PERMISSIONS,
    PermissionPreset,
    permission_engine,
)
from tests.mock_discord import MockGuild, MockMember, MockRole


@pytest.fixture
def mock_guild():
    guild = MockGuild()
    return guild


def test_dangerous_permissions_detected():
    perms = ["send_messages", "view_channel", "administrator", "manage_guild"]
    dangerous = permission_engine.check_dangerous_permissions(perms)
    assert "administrator" in dangerous
    assert "manage_guild" in dangerous
    assert "send_messages" not in dangerous


def test_dangerous_permissions_from_discord_object():
    p = discord.Permissions(administrator=True, kick_members=True, send_messages=True)
    dangerous = permission_engine.check_dangerous_permissions(p)
    assert "administrator" in dangerous
    assert "kick_members" in dangerous


def test_public_preset_overwrites(mock_guild):
    overwrites = permission_engine.build_overwrites_for_preset(mock_guild, PermissionPreset.PUBLIC)
    everyone = mock_guild.default_role
    assert everyone in overwrites
    assert overwrites[everyone].view_channel is True
    assert overwrites[everyone].send_messages is True


def test_private_preset_overwrites(mock_guild):
    role = MockRole(id=555, name="SecretRole", position=5)
    mock_guild.roles.append(role)
    overwrites = permission_engine.build_overwrites_for_preset(
        mock_guild, PermissionPreset.PRIVATE, selected_roles=[role]
    )
    everyone = mock_guild.default_role
    assert everyone in overwrites
    assert overwrites[everyone].view_channel is False
    assert role in overwrites
    assert overwrites[role].view_channel is True
    assert overwrites[role].send_messages is True


def test_ticket_preset_overwrites(mock_guild):
    opener = MockMember(id=444, name="TicketOpener", guild=mock_guild)
    overwrites = permission_engine.build_overwrites_for_preset(
        mock_guild, PermissionPreset.TICKET, ticket_opener=opener
    )
    everyone = mock_guild.default_role
    assert overwrites[everyone].view_channel is False
    assert overwrites[opener].view_channel is True
    assert overwrites[opener].send_messages is True
    assert overwrites[opener].attach_files is True


def test_bot_hierarchy_checks(mock_guild):
    high_role = MockRole(id=1, name="HigherRole", position=200)
    low_role = MockRole(id=2, name="LowerRole", position=50)
    mock_guild.roles.extend([high_role, low_role])

    # Bot role is at position 100
    assert permission_engine.bot_can_manage_role(mock_guild, low_role) is True
    assert permission_engine.bot_can_manage_role(mock_guild, high_role) is False
