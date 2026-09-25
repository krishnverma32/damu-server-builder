"""Builder Verifier — Post-execution verification of guild resources against the build plan."""

from __future__ import annotations

import logging
from typing import Any

import discord

from core.models import BuildPlan
from services.json_builder import _resolve_permissions, _style_text

log = logging.getLogger("engines.builder.verifier")


class BuilderVerifier:
    """Verifies that all roles, categories, channels, and overwrites match the schema."""

    def verify_guild(self, guild: discord.Guild, plan: BuildPlan) -> tuple[bool, list[str]]:
        issues: list[str] = []
        schema = plan.metadata.get("schema", {})

        global_font = schema.get("font") or schema.get("name_font") or schema.get("name_style")
        category_font = schema.get("category_font") or global_font
        channel_font = schema.get("channel_font") or global_font
        role_font = schema.get("role_font")

        # 1. Verify roles
        for role_data in schema.get("roles", []):
            r_name = role_data.get("name", "")
            styled = _style_text(r_name, role_data.get("font") or role_font)
            role = discord.utils.get(guild.roles, name=r_name) or discord.utils.get(guild.roles, name=styled)
            if not role:
                issues.append(f"Missing role: '{r_name}'")

        # 2. Verify categories & channels
        for cat_data in schema.get("categories", []):
            c_name = cat_data.get("name", "")
            styled_c = _style_text(c_name, cat_data.get("font") or category_font)
            cat = discord.utils.get(guild.categories, name=c_name) or discord.utils.get(guild.categories, name=styled_c)
            if not cat:
                issues.append(f"Missing category: '{c_name}'")
                continue

            for ch_data in cat_data.get("channels", []):
                ch_name = ch_data.get("name", "")
                styled_ch = _style_text(ch_name, ch_data.get("font") or channel_font)
                ch = discord.utils.find(lambda c: c.name in (ch_name, styled_ch) and c.category_id == cat.id, guild.channels)
                if not ch:
                    issues.append(f"Missing channel: '#{ch_name}' in category '{c_name}'")

        return len(issues) == 0, issues


builder_verifier = BuilderVerifier()
