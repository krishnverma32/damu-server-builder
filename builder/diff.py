"""Deterministic server configuration diff and conflict detection engine."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

import discord

from builder.models import ServerConfig
from builder.names import _styled_name
from builder.permissions import _PERM_MAP, _resolve_permissions

log = logging.getLogger(__name__)


@dataclass
class ResourceChange:
    action: str  # "create", "reuse", "update", "skip", "delete"
    resource_type: str  # "role", "category", "channel"
    name: str
    details: str = ""
    resource_id: int | None = None


@dataclass
class ServerDiffResult:
    roles_create: list[ResourceChange] = field(default_factory=list)
    roles_update: list[ResourceChange] = field(default_factory=list)
    roles_reuse: list[ResourceChange] = field(default_factory=list)
    roles_delete: list[ResourceChange] = field(default_factory=list)

    categories_create: list[ResourceChange] = field(default_factory=list)
    categories_update: list[ResourceChange] = field(default_factory=list)
    categories_reuse: list[ResourceChange] = field(default_factory=list)
    categories_delete: list[ResourceChange] = field(default_factory=list)

    channels_create: list[ResourceChange] = field(default_factory=list)
    channels_update: list[ResourceChange] = field(default_factory=list)
    channels_reuse: list[ResourceChange] = field(default_factory=list)
    channels_delete: list[ResourceChange] = field(default_factory=list)

    overwrites_changes: int = 0
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def total_creations(self) -> int:
        return len(self.roles_create) + len(self.categories_create) + len(self.channels_create)

    def total_updates(self) -> int:
        return len(self.roles_update) + len(self.categories_update) + len(self.channels_update)

    def total_deletions(self) -> int:
        return len(self.roles_delete) + len(self.categories_delete) + len(self.channels_delete)

    def format_diff_text(self) -> str:
        lines = ["═══ SERVER DIFFERENCE ═══\n"]

        if self.roles_create or self.roles_update or self.roles_delete:
            lines.append("Roles:")
            for c in self.roles_create:
                lines.append(f"  + @{c.name} (Create)")
            for c in self.roles_update:
                lines.append(f"  ~ @{c.name} (Update: {c.details})")
            for c in self.roles_delete:
                lines.append(f"  - @{c.name} (Delete)")
            lines.append("")

        if self.categories_create or self.categories_update or self.categories_delete:
            lines.append("Categories:")
            for c in self.categories_create:
                lines.append(f"  + {c.name} (Create)")
            for c in self.categories_update:
                lines.append(f"  ~ {c.name} (Update)")
            for c in self.categories_delete:
                lines.append(f"  - {c.name} (Delete)")
            lines.append("")

        if self.channels_create or self.channels_update or self.channels_delete:
            lines.append("Channels:")
            for c in self.channels_create:
                lines.append(f"  + #{c.name} (Create)")
            for c in self.channels_update:
                lines.append(f"  ~ #{c.name} (Update: {c.details})")
            for c in self.channels_delete:
                lines.append(f"  - #{c.name} (Delete)")
            lines.append("")

        lines.append(f"Permissions: ~ {self.overwrites_changes} overwrites configured")

        if self.conflicts:
            lines.append("\n⚠️ Conflicts / Blocking Issues:")
            for conflict in self.conflicts:
                lines.append(f"  • {conflict}")

        if self.warnings:
            lines.append("\n💡 Warnings:")
            for warning in self.warnings:
                lines.append(f"  • {warning}")

        return "\n".join(lines)


def calculate_server_diff(
    guild: discord.Guild,
    config: ServerConfig,
    *,
    clean_existing: bool = False,
    safe_channel_id: int | None = None,
) -> ServerDiffResult:
    """Side-effect-free comparison between guild state and desired ServerConfig."""
    schema = config.to_dict()
    result = ServerDiffResult()
    me = guild.me

    existing_roles = {r.name: r for r in guild.roles}
    existing_categories = {c.name: c for c in guild.categories}
    existing_channels = {c.name: c for c in guild.channels}

    # 1. Roles Diff
    seen_role_names: set[str] = set()
    for role_data in schema.get("roles", []):
        r_name = _styled_name(role_data, schema.get("role_font"))
        if r_name in seen_role_names:
            result.conflicts.append(f"Duplicate role in configuration: '{r_name}'")
        seen_role_names.add(r_name)

        if r_name in existing_roles:
            role_obj = existing_roles[r_name]
            result.roles_reuse.append(ResourceChange("reuse", "role", r_name, resource_id=role_obj.id))
            if me and role_obj >= me.top_role and not role_obj.is_default():
                result.conflicts.append(f"Existing role '{r_name}' is equal to or above Damu's highest role.")
        else:
            result.roles_create.append(ResourceChange("create", "role", r_name))
            if me and not me.guild_permissions.manage_roles:
                result.conflicts.append("Bot lacks 'Manage Roles' permission to create new roles.")

    # 2. Categories & Channels Diff
    seen_cat_names: set[str] = set()
    seen_ch_names: set[str] = set()

    for cat_data in schema.get("categories", []):
        c_name = _styled_name(cat_data, schema.get("category_font"))
        if c_name in seen_cat_names:
            result.conflicts.append(f"Duplicate category in configuration: '{c_name}'")
        seen_cat_names.add(c_name)

        cat_overwrites = len(cat_data.get("permission_overwrites", []))
        result.overwrites_changes += cat_overwrites

        if c_name in existing_categories:
            cat_obj = existing_categories[c_name]
            result.categories_reuse.append(ResourceChange("reuse", "category", c_name, resource_id=cat_obj.id))
        else:
            result.categories_create.append(ResourceChange("create", "category", c_name))

        for ch_data in cat_data.get("channels", []):
            ch_name = _styled_name(ch_data, schema.get("channel_font"))
            if ch_name in seen_ch_names:
                result.conflicts.append(f"Duplicate channel name in configuration: '{ch_name}'")
            seen_ch_names.add(ch_name)

            ch_overwrites = len(ch_data.get("permission_overwrites", []))
            result.overwrites_changes += ch_overwrites

            ch_type = ch_data.get("type", "text")
            if ch_type == "forum" and "COMMUNITY" not in guild.features:
                result.conflicts.append(f"Channel '{ch_name}' is a forum, but server does not have Community enabled.")

            if ch_name in existing_channels:
                ch_obj = existing_channels[ch_name]
                result.channels_reuse.append(ResourceChange("reuse", "channel", ch_name, resource_id=ch_obj.id))
                result.warnings.append(f"Channel '#{ch_name}' already exists. A duplicate will be created if unmanaged.")
            else:
                result.channels_create.append(ResourceChange("create", "channel", ch_name))

    # 3. Clean existing / Deletions
    if clean_existing:
        safe_category_id = None
        if safe_channel_id:
            safe_ch = guild.get_channel(safe_channel_id)
            if safe_ch:
                safe_category_id = getattr(safe_ch, "category_id", None)

        for ch in guild.channels:
            if ch.id != safe_channel_id and ch.id != safe_category_id:
                if isinstance(ch, discord.CategoryChannel):
                    result.categories_delete.append(ResourceChange("delete", "category", ch.name, resource_id=ch.id))
                else:
                    result.channels_delete.append(ResourceChange("delete", "channel", ch.name, resource_id=ch.id))

        for r in guild.roles:
            if not r.is_default() and not r.managed and (me is None or r < me.top_role):
                result.roles_delete.append(ResourceChange("delete", "role", r.name, resource_id=r.id))

    return result
