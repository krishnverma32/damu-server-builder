"""Tests for schema validation and ServerConfig modeling."""
from __future__ import annotations

import pytest
from builder.exceptions import ConfigurationError
from builder.models import ServerConfig
from builder.validator import parse_json, validate_config


def test_valid_basic_config():
    data = {
        "server_name": "Test Guild",
        "roles": [
            {"name": "Admin", "color": "red", "hoist": True, "mentionable": True, "permissions": ["administrator"]},
            {"name": "Member", "color": "blue", "permissions": ["send_messages", "view_channel"]},
        ],
        "categories": [
            {
                "name": "General",
                "channels": [
                    {"name": "welcome", "type": "text", "topic": "Welcome to the server"},
                    {"name": "voice-lounge", "type": "voice", "bitrate": 64000},
                    {"name": "announcements", "type": "announcement"},
                    {"name": "stage-events", "type": "stage"},
                    {"name": "discussion", "type": "forum"},
                ],
            }
        ],
    }
    validated = validate_config(data)
    assert validated["server_name"] == "Test Guild"
    assert len(validated["roles"]) == 2
    assert len(validated["categories"][0]["channels"]) == 5

    config = ServerConfig.from_dict(data)
    assert config.to_dict()["server_name"] == "Test Guild"


def test_member_and_role_overwrites():
    data = {
        "roles": [{"name": "Admin"}],
        "categories": [
            {
                "name": "Staff Area",
                "permission_overwrites": [
                    {"role": "@everyone", "deny": ["view_channel"]},
                    {"role": "Admin", "allow": ["view_channel", "send_messages"]},
                    {"member": "123456789012345678", "allow": ["view_channel"]},
                ],
                "channels": [
                    {
                        "name": "private-room",
                        "type": "text",
                        "permission_overwrites": [
                            {"member": "987654321098765432", "allow": ["send_messages"]},
                        ],
                    }
                ],
            }
        ],
    }
    validated = validate_config(data)
    assert len(validated["categories"][0]["permission_overwrites"]) == 3
    assert validated["categories"][0]["permission_overwrites"][2]["member"] == "123456789012345678"


def test_invalid_channel_type_rejected():
    data = {
        "categories": [
            {
                "name": "General",
                "channels": [{"name": "bad-channel", "type": "invalid_type"}],
            }
        ]
    }
    with pytest.raises(ConfigurationError) as exc_info:
        validate_config(data)
    assert any("invalid_type" in err or "type" in err for err in exc_info.value.issues)


def test_parse_json_valid_and_invalid():
    valid_json = '{"server_name": "JSON Guild", "roles": [], "categories": []}'
    parsed = parse_json(valid_json)
    assert parsed["server_name"] == "JSON Guild"

    with pytest.raises(ConfigurationError):
        parse_json('{"bad_json": incomplete')
