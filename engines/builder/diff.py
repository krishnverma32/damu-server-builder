"""Diff Engine — Computes diffs between current guild state and requested target state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import discord

log = logging.getLogger("engines.builder.diff")


@dataclass
class ResourceDiff:
    resource_type: str  # "role", "category", "channel"
    name: str
    change_type: str  # "create", "modify", "delete", "unchanged"
    details: list[str] = field(default_factory=list)


@dataclass
class ServerDiffReport:
    roles_diff: list[ResourceDiff] = field(default_factory=list)
    categories_diff: list[ResourceDiff] = field(default_factory=list)
    channels_diff: list[ResourceDiff] = field(default_factory=list)
    summary: str = ""

    @property
    def has_changes(self) -> bool:
        return any(
            d.change_type != "unchanged"
            for d in self.roles_diff + self.categories_diff + self.channels_diff
        )

    def format_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔍 SERVER CONFIGURATION DIFF",
            description=self.summary or "Comparison between current guild state and proposed plan.",
            colour=0x5865F2,
        )

        to_add_roles = [r.name for r in self.roles_diff if r.change_type == "create"]
        if to_add_roles:
            embed.add_field(name="➕ Roles to Create", value=", ".join(to_add_roles[:15]), inline=False)

        to_add_cats = [c.name for c in self.categories_diff if c.change_type == "create"]
        if to_add_cats:
            embed.add_field(name="➕ Categories to Create", value=", ".join(to_add_cats[:10]), inline=False)

        to_add_chs = [c.name for c in self.channels_diff if c.change_type == "create"]
        if to_add_chs:
            embed.add_field(name="➕ Channels to Create", value=", ".join(f"#{c}" for c in to_add_chs[:15]), inline=False)

        modifications: list[str] = []
        for diff in self.channels_diff + self.roles_diff:
            if diff.change_type == "modify":
                modifications.append(f"**{diff.name}**: {'; '.join(diff.details)}")
        if modifications:
            embed.add_field(name="✏️ Modified Permissions / Settings", value="\n".join(modifications[:8]), inline=False)

        return embed


class DiffEngine:
    """Computes differences between existing guild structures and requested schemas."""

    def compare_schema(self, guild: discord.Guild, schema: dict[str, Any]) -> ServerDiffReport:
        report = ServerDiffReport()

        existing_role_names = {r.name.lower(): r for r in guild.roles}
        for role_data in schema.get("roles", []):
            r_name = role_data.get("name", "")
            if r_name.lower() in existing_role_names:
                report.roles_diff.append(ResourceDiff("role", r_name, "unchanged"))
            else:
                report.roles_diff.append(ResourceDiff("role", r_name, "create", ["New role addition"]))

        existing_cat_names = {c.name.lower(): c for c in guild.categories}
        for cat_data in schema.get("categories", []):
            c_name = cat_data.get("name", "")
            cat_obj = existing_cat_names.get(c_name.lower())
            if cat_obj:
                report.categories_diff.append(ResourceDiff("category", c_name, "unchanged"))
            else:
                report.categories_diff.append(ResourceDiff("category", c_name, "create", ["New category addition"]))

            # Inspect channels in category
            existing_ch_names = {ch.name.lower(): ch for ch in (cat_obj.channels if cat_obj else [])}
            for ch_data in cat_data.get("channels", []):
                ch_name = ch_data.get("name", "")
                if ch_name.lower() in existing_ch_names:
                    report.channels_diff.append(ResourceDiff("channel", ch_name, "unchanged"))
                else:
                    report.channels_diff.append(ResourceDiff("channel", ch_name, "create", [f"In category '{c_name}'"]))

        create_count = sum(1 for d in report.roles_diff + report.categories_diff + report.channels_diff if d.change_type == "create")
        report.summary = f"Identified **{create_count}** resources to create across roles, categories, and channels."
        return report


diff_engine = DiffEngine()
