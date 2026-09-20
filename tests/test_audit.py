"""Tests for server security audit and safe fix engine."""
from __future__ import annotations

from unittest.mock import MagicMock
import discord
from builder.audit import AuditFinding, AuditReport, run_server_audit


def test_audit_report_summary():
    report = AuditReport()
    report.critical.append(
        AuditFinding(
            level="critical",
            title="Dangerous Permission",
            what_is_wrong="Admin on @everyone",
            why_it_matters="Members can do anything",
            how_to_fix="Revoke admin",
            fix_id="revoke_everyone_dangerous",
        )
    )
    report.warning.append(
        AuditFinding(
            level="warning",
            title="Mention Everyone",
            what_is_wrong="Spam possible",
            why_it_matters="Ping all members",
            how_to_fix="Disable it",
            fix_id="disable_everyone_mention",
        )
    )
    report.healthy.append(AuditFinding("healthy", "Role Hierarchy", "", "", ""))

    embed = report.summary_embed("Test Guild")
    assert "Critical:** 1" in embed.description
    assert "Recommendations:** 1" in embed.description
    assert "Healthy:** 1" in embed.description


def test_run_server_audit_finds_dangerous_everyone():
    guild = MagicMock(spec=discord.Guild)
    guild.name = "Vulnerable Server"
    guild.roles = []
    guild.text_channels = []

    default_role = MagicMock(spec=discord.Role)
    perms = discord.Permissions.all()  # Dangerous!
    default_role.permissions = perms
    guild.default_role = default_role

    me = MagicMock(spec=discord.Member)
    me.guild_permissions = discord.Permissions.all()
    me.top_role = MagicMock(spec=discord.Role)
    me.top_role.position = 10
    guild.me = me

    report = run_server_audit(guild)
    assert len(report.critical) > 0
    assert any("administrator" in f.what_is_wrong.lower() or "privileged" in f.title.lower() for f in report.critical)
