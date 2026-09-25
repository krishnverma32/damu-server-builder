"""Tests for Schema Validation and Diff Engine."""

from __future__ import annotations

import pytest

from core.errors import ValidationError
from engines.builder.diff import diff_engine
from engines.builder.schema import schema_validator
from tests.mock_discord import MockGuild


def test_valid_schema():
    valid = {
        "server_name": "Test Server",
        "roles": [{"name": "Member", "permissions": ["send_messages"]}],
        "categories": [
            {
                "name": "General",
                "channels": [{"name": "chat", "type": "text"}],
            }
        ],
    }
    res = schema_validator.parse_and_validate(valid)
    assert res["server_name"] == "Test Server"


def test_invalid_channel_type_rejected():
    invalid = {
        "roles": [],
        "categories": [
            {
                "name": "General",
                "channels": [{"name": "invalid-ch", "type": "telepathy"}],
            }
        ],
    }
    with pytest.raises(ValidationError) as exc:
        schema_validator.parse_and_validate(invalid)
    assert "unsupported type" in str(exc.value)


def test_schema_security_warnings():
    risky = {
        "roles": [
            {"name": "SuperAdmin", "permissions": ["administrator", "manage_guild"]},
        ],
        "categories": [],
    }
    warns = schema_validator.check_security(risky)
    assert any("administrator" in w.lower() for w in warns)


def test_diff_engine_compares_guild():
    guild = MockGuild()
    schema = {
        "roles": [{"name": "NewRole", "permissions": []}],
        "categories": [
            {
                "name": "NewCategory",
                "channels": [{"name": "new-chat", "type": "text"}],
            }
        ],
    }
    diff = diff_engine.compare_schema(guild, schema)
    assert diff.has_changes is True
    assert any(r.name == "NewRole" and r.change_type == "create" for r in diff.roles_diff)
    assert any(c.name == "NewCategory" and c.change_type == "create" for c in diff.categories_diff)
