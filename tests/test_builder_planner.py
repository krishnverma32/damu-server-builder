"""Tests for Builder Planner."""

from __future__ import annotations

import pytest

from core.models import RiskLevel
from engines.builder.planner import builder_planner
from tests.mock_discord import MockGuild, MockMember


@pytest.fixture
def planner_setup():
    guild = MockGuild()
    user = MockMember(id=99, name="AdminUser", guild=guild)
    return guild, user


def test_builder_planner_creates_actions(planner_setup):
    guild, user = planner_setup
    schema = {
        "roles": [{"name": "Admin", "permissions": ["kick_members"]}],
        "categories": [
            {
                "name": "General",
                "channels": [{"name": "welcome", "type": "text"}],
            }
        ],
    }

    plan = builder_planner.create_plan_from_schema(guild, user, schema)
    assert plan.guild_id == guild.id
    assert plan.total_actions() == 3  # 1 role, 1 category, 1 channel
    assert plan.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)


def test_builder_planner_flags_administrator_as_critical(planner_setup):
    guild, user = planner_setup
    schema = {
        "roles": [{"name": "Owner", "permissions": ["administrator"]}],
        "categories": [],
    }

    plan = builder_planner.create_plan_from_schema(guild, user, schema)
    assert plan.risk_level == RiskLevel.CRITICAL
    assert plan.requires_confirmation is True
    assert any("administrator" in w.lower() for w in plan.warnings)
