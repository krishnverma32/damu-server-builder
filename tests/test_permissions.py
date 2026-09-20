"""Tests for permissions resolution, three-state modeling, and presets."""
from __future__ import annotations

import discord
import pytest
from builder.permissions import (
    PERMISSION_CATEGORIES,
    PERMISSION_PRESETS,
    ROLE_PRESETS,
    _resolve_permissions,
    overwrite_to_tri_state,
    tri_state_to_overwrite,
)


def test_resolve_permissions():
    perms = _resolve_permissions(["send_messages", "view_channel"])
    assert perms.send_messages is True
    assert perms.view_channel is True
    assert perms.administrator is False

    admin_perms = _resolve_permissions(["administrator"])
    assert admin_perms.administrator is True

    with pytest.raises(ValueError, match="Unknown permission name"):
        _resolve_permissions(["not_a_real_permission"])


def test_tri_state_to_overwrite_and_back():
    states = {
        "view_channel": True,
        "send_messages": False,
        "attach_files": None,
    }
    ow = tri_state_to_overwrite(states)
    assert ow.view_channel is True
    assert ow.send_messages is False
    assert ow.attach_files is None

    extracted = overwrite_to_tri_state(ow)
    assert extracted.get("view_channel") is True
    assert extracted.get("send_messages") is False
    assert extracted.get("attach_files") is None


def test_permission_presets_structure():
    assert "Public Chat" in PERMISSION_PRESETS
    assert "Announcement" in PERMISSION_PRESETS
    assert "Staff Only" in PERMISSION_PRESETS
    assert "VIP Only" in PERMISSION_PRESETS

    for name, preset in PERMISSION_PRESETS.items():
        assert len(preset) > 0
        for target, rules in preset.items():
            assert "allow" in rules
            assert "deny" in rules
            assert isinstance(rules["allow"], list)
            assert isinstance(rules["deny"], list)


def test_role_presets_structure():
    assert "Admin" in ROLE_PRESETS
    assert "Moderator" in ROLE_PRESETS
    assert "VIP" in ROLE_PRESETS
    assert "Verified Member" in ROLE_PRESETS

    for name, preset in ROLE_PRESETS.items():
        assert "permissions" in preset
        assert isinstance(preset["permissions"], list)
        # Ensure all listed permissions resolve without error
        _resolve_permissions(preset["permissions"])


def test_permission_categories():
    assert "GENERAL" in PERMISSION_CATEGORIES
    assert "MESSAGES" in PERMISSION_CATEGORIES
    assert "MODERATION" in PERMISSION_CATEGORIES
    assert "VOICE" in PERMISSION_CATEGORIES

    for cat_name, perms in PERMISSION_CATEGORIES.items():
        for p in perms:
            # Each perm must resolve
            _resolve_permissions([p])
