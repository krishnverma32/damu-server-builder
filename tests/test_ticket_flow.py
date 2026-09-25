"""Tests for Support Ticket System flow and safety."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.ticket_system import TicketSystem
from tests.mock_discord import MockCategoryChannel, MockGuild, MockInteraction, MockMember, MockRole


@pytest.fixture
def ticket_setup():
    guild = MockGuild()
    user = MockMember(id=501, name="HappyUser", guild=guild)
    support_role = MockRole(id=601, name="Support Staff", position=10)
    category = MockCategoryChannel(id=701, name="TICKETS", guild=guild)
    guild.roles.append(support_role)
    guild.categories.append(category)
    guild.channels.append(category)

    bot = MagicMock()
    cog = TicketSystem(bot)
    # Ensure offline execution without connecting to remote DB
    cog.config_manager.col = None

    # Configure mock guild config
    cog.config_manager._memory_cache[str(guild.id)] = {
        "support_role_id": support_role.id,
        "mod_role_id": support_role.id,
        "ticket_category_id": category.id,
        "ticket_counter": 0,
        "open_tickets": {},
        "blacklisted_users": [],
    }

    return guild, user, cog


def _get_followup_content(inter: MockInteraction) -> str:
    call_args = inter.followup.send.call_args
    if not call_args:
        return ""
    if call_args.args:
        return str(call_args.args[0])
    return str(call_args.kwargs.get("content", ""))


@pytest.mark.anyio
async def test_ticket_creation_acknowledges_immediately(ticket_setup):
    guild, user, cog = ticket_setup
    inter = MockInteraction(guild=guild, user=user)

    await cog.create_ticket(inter, "Tech Support")

    # Verify interaction was deferred immediately
    assert inter.response.defer.called
    # Verify followup message was sent
    assert inter.followup.send.called
    assert "Your ticket has been created" in _get_followup_content(inter)


@pytest.mark.anyio
async def test_ticket_creation_blocks_blacklisted_user(ticket_setup):
    guild, user, cog = ticket_setup
    cog.config_manager._memory_cache[str(guild.id)]["blacklisted_users"].append(user.id)
    inter = MockInteraction(guild=guild, user=user)

    await cog.create_ticket(inter, "Tech Support")
    assert "not permitted to open tickets" in _get_followup_content(inter)


@pytest.mark.anyio
async def test_ticket_creation_blocks_duplicate(ticket_setup):
    guild, user, cog = ticket_setup
    inter1 = MockInteraction(guild=guild, user=user)
    await cog.create_ticket(inter1, "Tech Support")

    # Second attempt
    inter2 = MockInteraction(guild=guild, user=user)
    await cog.create_ticket(inter2, "Tech Support")
    assert "already have an open ticket" in _get_followup_content(inter2)


@pytest.mark.anyio
async def test_ticket_creation_missing_category(ticket_setup):
    guild, user, cog = ticket_setup
    # Point to nonexistent category
    cog.config_manager._memory_cache[str(guild.id)]["ticket_category_id"] = 99999
    inter = MockInteraction(guild=guild, user=user)

    await cog.create_ticket(inter, "Server Support")
    assert "Ticket category not found" in _get_followup_content(inter)
