"""Tests for AI Safety Validator and Fallback Planner."""

from __future__ import annotations

import pytest

from core.errors import ValidationError
from engines.intelligence.planner import intelligence_planner
from engines.intelligence.validator import ai_safety_validator
from tests.mock_discord import MockGuild, MockMember


def test_validator_repairs_json_markdown():
    raw = "```json\n{\n  \"server_name\": \"Cool Guild\",\n  \"roles\": [],\n  \"categories\": []\n}\n```"
    parsed = ai_safety_validator.parse_and_repair_json(raw)
    assert parsed["server_name"] == "Cool Guild"


def test_validator_strips_administrator_from_ai():
    data = {
        "roles": [{"name": "SneakyRole", "permissions": ["administrator", "send_messages"]}],
        "categories": [],
    }
    valid, validated, warnings = ai_safety_validator.validate_plan(data)
    assert valid is True
    role = validated["roles"][0]
    assert "administrator" not in role["permissions"]
    assert "send_messages" in role["permissions"]
    assert any("administrator stripped" in w.lower() for w in warnings)


@pytest.mark.anyio
async def test_intelligence_planner_fallback_on_ai_failure():
    guild = MockGuild()
    user = MockMember(id=88, name="FallbackUser", guild=guild)

    # Prompt requesting a private channel
    prompt = "Create a private staff support channel"
    schema, tier, warnings = await intelligence_planner.plan_request(guild, user, prompt)

    assert schema is not None
    assert tier in ("RULE_BASED", "FALLBACK_PRESET", "TEMPLATE_PRESET")
    assert len(schema.get("categories", [])) >= 1
