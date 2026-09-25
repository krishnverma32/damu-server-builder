"""Tests for Role Resolver and semantic mapping."""

from __future__ import annotations

import pytest

from engines.guild.role_resolver import RoleResolver
from tests.mock_discord import MockGuild, MockRole


@pytest.fixture
def resolver_guild():
    guild = MockGuild()
    mod_role = MockRole(id=101, name="Moderator", position=10)
    admin_role = MockRole(id=102, name="Administrator", position=20)
    vip_role = MockRole(id=103, name="VIP Supporter", position=5)
    guild.roles.extend([mod_role, admin_role, vip_role])
    return guild


def test_exact_role_resolution(resolver_guild):
    resolver = RoleResolver()
    res = resolver.resolve(resolver_guild, "Moderator")
    assert res.exact_match is not None
    assert res.exact_match.id == 101
    assert not res.is_ambiguous


def test_alias_role_resolution(resolver_guild):
    resolver = RoleResolver()
    res = resolver.resolve(resolver_guild, "admin")
    assert res.best_role is not None
    assert res.best_role.id == 102  # "Administrator"


def test_ambiguous_role_resolution(resolver_guild):
    resolver = RoleResolver()
    sr_mod = MockRole(id=104, name="Senior Moderator", position=12)
    resolver_guild.roles.append(sr_mod)

    res = resolver.resolve(resolver_guild, "mod")
    # Both Moderator and Senior Moderator match with similar confidence
    assert len(res.matches) >= 2
    assert res.is_ambiguous is True


def test_cached_role_resolution(resolver_guild):
    resolver = RoleResolver()
    resolver.set_cached_role(resolver_guild.id, "custom_support", 103)

    res = resolver.resolve(resolver_guild, "custom_support")
    assert res.exact_match is not None
    assert res.exact_match.id == 103
