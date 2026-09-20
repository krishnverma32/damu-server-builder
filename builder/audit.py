"""Server audit and security scanning engine with guided safe fixes."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Callable, Coroutine

import discord

from builder.validator import DANGEROUS_PERMISSIONS
from services.embed_service import info_embed

log = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    level: str  # "critical", "warning", "healthy"
    title: str
    what_is_wrong: str
    why_it_matters: str
    how_to_fix: str
    fix_id: str | None = None
    target_id: int | None = None


@dataclass
class AuditReport:
    critical: list[AuditFinding] = field(default_factory=list)
    warning: list[AuditFinding] = field(default_factory=list)
    healthy: list[AuditFinding] = field(default_factory=list)

    def summary_embed(self, guild_name: str) -> discord.Embed:
        embed = info_embed(
            f"🛡️ Server Audit — {guild_name}",
            f"**🔴 Critical:** {len(self.critical)}  |  "
            f"**🟡 Recommendations:** {len(self.warning)}  |  "
            f"**🟢 Healthy:** {len(self.healthy)}\n\n"
            "Review findings below. Run `/server fix` to apply safe automated remediations.",
        )

        for item in self.critical[:5]:
            embed.add_field(
                name=f"🔴 {item.title}",
                value=f"**Problem:** {item.what_is_wrong}\n**Impact:** {item.why_it_matters}\n**Fix:** {item.how_to_fix}",
                inline=False,
            )

        for item in self.warning[:5]:
            embed.add_field(
                name=f"🟡 {item.title}",
                value=f"**Recommendation:** {item.what_is_wrong}\n**Fix:** {item.how_to_fix}",
                inline=False,
            )

        if not self.critical and not self.warning:
            embed.add_field(
                name="✨ Perfect Security Score",
                value="No critical or recommended issues detected. Your server configuration follows best practices.",
                inline=False,
            )

        embed.set_footer(text=f"Total checks performed: {len(self.critical) + len(self.warning) + len(self.healthy)}")
        return embed


def run_server_audit(guild: discord.Guild) -> AuditReport:
    """Perform security and configuration audit on guild."""
    report = AuditReport()
    me = guild.me

    # 1. Bot permissions check
    if me:
        perms = me.guild_permissions
        if not perms.administrator and not (perms.manage_roles and perms.manage_channels):
            report.critical.append(
                AuditFinding(
                    level="critical",
                    title="Bot Lacks Management Permissions",
                    what_is_wrong="Damu does not have Administrator or (Manage Roles + Manage Channels).",
                    why_it_matters="Damu cannot create channels, configure permissions, or execute builds.",
                    how_to_fix="Grant the Damu bot role 'Manage Roles' and 'Manage Channels', or 'Administrator'.",
                )
            )
        else:
            report.healthy.append(
                AuditFinding("healthy", "Bot Permissions", "", "", "")
            )

    # 2. Bot role hierarchy check
    if me and me.top_role.position < len(guild.roles) - 3:
        report.warning.append(
            AuditFinding(
                level="warning",
                title="Bot Role Position Low in Hierarchy",
                what_is_wrong=f"Damu's highest role is '{me.top_role.name}' at position {me.top_role.position}.",
                why_it_matters="Discord's hierarchy prevents Damu from managing roles placed above its own.",
                how_to_fix="In Server Settings > Roles, drag the Damu bot role closer to the top.",
            )
        )
    else:
        report.healthy.append(AuditFinding("healthy", "Role Hierarchy", "", "", ""))

    # 3. Dangerous @everyone permissions
    default_role = guild.default_role
    dangerous_present: list[str] = []
    for perm_name in DANGEROUS_PERMISSIONS:
        if getattr(default_role.permissions, perm_name, False):
            dangerous_present.append(perm_name)

    if dangerous_present:
        report.critical.append(
            AuditFinding(
                level="critical",
                title="@everyone Has Privileged Permissions",
                what_is_wrong=f"@everyone role has: {', '.join(dangerous_present)}.",
                why_it_matters="Any member joining your server immediately gets dangerous admin/moderator abilities.",
                how_to_fix=f"Revoke {', '.join(dangerous_present)} from @everyone.",
                fix_id="revoke_everyone_dangerous",
            )
        )
    else:
        report.healthy.append(AuditFinding("healthy", "@everyone Role Security", "", "", ""))

    # 4. Mention everyone in @everyone
    if default_role.permissions.mention_everyone:
        report.warning.append(
            AuditFinding(
                level="warning",
                title="@everyone Can Mention @everyone / @here",
                what_is_wrong="@everyone role has 'Mention @everyone, @here, and All Roles' enabled.",
                why_it_matters="Allows raids or members to ping the entire server, creating spam.",
                how_to_fix="Disable 'Mention Everyone' for @everyone in Server Settings > Roles.",
                fix_id="disable_everyone_mention",
            )
        )
    else:
        report.healthy.append(AuditFinding("healthy", "Mention Everyone Restriction", "", "", ""))

    # 5. Announcement and Rules channels security
    announcement_keywords = ("rules", "rule", "announcement", "announcements", "news", "updates")
    for ch in guild.text_channels:
        if any(kw in ch.name.lower() for kw in announcement_keywords):
            ow = ch.overwrites_for(default_role)
            # If send_messages is not explicitly False:
            if ow.send_messages is not False:
                report.critical.append(
                    AuditFinding(
                        level="critical",
                        title=f"Public Posting in #{ch.name}",
                        what_is_wrong=f"Channel #{ch.name} allows normal members or @everyone to send messages.",
                        why_it_matters="Announcement/rules channels can be polluted with chat spam.",
                        how_to_fix=f"Deny 'Send Messages' for @everyone in #{ch.name}.",
                        fix_id=f"lock_announcement_{ch.id}",
                        target_id=ch.id,
                    )
                )
            else:
                report.healthy.append(AuditFinding("healthy", f"Channel #{ch.name} Protected", "", "", ""))

    # 6. Logging channel check
    log_channel_exists = any("log" in ch.name.lower() or "audit" in ch.name.lower() for ch in guild.text_channels)
    if not log_channel_exists:
        report.warning.append(
            AuditFinding(
                level="warning",
                title="No Moderation/Audit Log Channel Found",
                what_is_wrong="No text channel with 'log' or 'audit' in its name was found.",
                why_it_matters="Moderation events, member bans, and edits will not be logged publicly for staff.",
                how_to_fix="Create a private `#mod-logs` channel for staff.",
                fix_id="create_mod_log_channel",
            )
        )
    else:
        report.healthy.append(AuditFinding("healthy", "Staff Log Channel", "", "", ""))

    return report


async def apply_safe_fix(
    guild: discord.Guild,
    finding: AuditFinding,
) -> str:
    """Safely apply a targeted fix for a detected issue."""
    if finding.fix_id == "disable_everyone_mention":
        perms = guild.default_role.permissions
        perms.mention_everyone = False
        await guild.default_role.edit(permissions=perms, reason="Damu Server Fix: disable mention_everyone")
        return "Disabled 'Mention Everyone' for @everyone."

    if finding.fix_id == "revoke_everyone_dangerous":
        perms = guild.default_role.permissions
        for p in DANGEROUS_PERMISSIONS:
            setattr(perms, p, False)
        await guild.default_role.edit(permissions=perms, reason="Damu Server Fix: revoke dangerous perms from @everyone")
        return "Revoked all dangerous permissions from @everyone."

    if finding.fix_id and finding.fix_id.startswith("lock_announcement_") and finding.target_id:
        ch = guild.get_channel(finding.target_id)
        if isinstance(ch, discord.TextChannel):
            await ch.set_permissions(
                guild.default_role,
                send_messages=False,
                send_messages_in_threads=False,
                reason="Damu Server Fix: lock announcement channel",
            )
            return f"Locked #{ch.name} so @everyone cannot send messages."

    if finding.fix_id == "create_mod_log_channel":
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        ch = await guild.create_text_channel("mod-logs", overwrites=overwrites, reason="Damu Server Fix: create log channel")
        return f"Created private staff log channel {ch.mention}."

    return "No automated fix available for this finding."
