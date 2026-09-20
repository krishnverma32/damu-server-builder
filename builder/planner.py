"""Side-effect-free preflight matching the create/reuse behavior of the engine."""
from __future__ import annotations

from typing import Any

import discord

from builder.models import BuildPlan, PlanStep, ServerConfig
from builder.names import _style_text, _styled_name
from builder.permissions import _resolve_permissions
from builder.validator import DANGEROUS_PERMISSIONS


def resolve_role(
    guild: discord.Guild, data: dict[str, Any], role_font: str | None,
    selected_roles: dict[str, discord.Role], skip_existing: bool = True,
    excluded_ids: set[int] | None = None,
) -> discord.Role | None:
    """One role matching policy used by both planner and executor."""
    selected = selected_roles.get(data["name"])
    if selected is None and "administrator" in data.get("permissions", []):
        selected = selected_roles.get("Admin") or selected_roles.get("Administrator")
    if selected is None and any(word in data["name"].lower() for word in ("mod", "moderator")):
        selected = selected_roles.get("Mod") or selected_roles.get("Moderator")
    if selected is not None:
        return selected
    if skip_existing:
        names = {data["name"], _styled_name(data, role_font)}
        candidates = [r for r in guild.roles if r.name in names and r.id not in (excluded_ids or set())]
        if len(candidates) > 1:
            raise ValueError(f"Multiple roles match {data['name']!r}; select a role explicitly or rename duplicates.")
        if candidates:
            return candidates[0]
    return None


def plan_build(
    guild: discord.Guild, config: ServerConfig, *,
    selected_roles: dict[str, discord.Role] | None = None,
    clean_existing: bool = False, safe_channel_id: int | None = None,
    skip_existing_roles: bool = True,
) -> BuildPlan:
    """Inspect cached guild state only. No REST calls, DB writes, or mutations."""
    schema = config.to_dict()
    selected_roles = selected_roles or {}
    steps: list[PlanStep] = []
    errors: list[str] = []
    warnings: list[str] = []
    me = guild.me
    if me is None:
        return BuildPlan(config, (), (), ("Bot member is unavailable; retry after the guild loads.",), 0)
    permissions = me.guild_permissions
    required: set[str] = set()
    if schema["roles"] or clean_existing:
        required.add("manage_roles")
    if schema["categories"] or clean_existing:
        required.add("manage_channels")
    if schema.get("server_name"):
        required.add("manage_guild")
    for name in required:
        if not getattr(permissions, name):
            errors.append(f"Damu needs {name.replace('_', ' ').title()} permission.")
    for role in selected_roles.values():
        if role.guild.id != guild.id or guild.get_role(role.id) is None:
            errors.append(f"Selected role {role.name!r} no longer exists in this server.")

    excluded: set[int] = set()
    deleted_channels: set[int] = set()
    if clean_existing:
        safe = guild.get_channel(safe_channel_id) if safe_channel_id else None
        if safe is None:
            errors.append("Destructive builds require an existing command channel to protect.")
        protected = {safe_channel_id, getattr(safe, "category_id", None)}
        protected_roles = {r.id for r in selected_roles.values()}
        # Child channels before their categories; never delete the command channel's category.
        for channel in sorted(guild.channels, key=lambda c: isinstance(c, discord.CategoryChannel)):
            if channel.id not in protected:
                kind = "category" if isinstance(channel, discord.CategoryChannel) else "channel"
                steps.append(PlanStep("delete", kind, channel.name, "existing", channel.id))
                deleted_channels.add(channel.id)
        for role in guild.roles:
            if role.id not in protected_roles and not role.is_default() and not role.managed and role < me.top_role:
                steps.append(PlanStep("delete", "role", role.name, "existing", role.id))
                excluded.add(role.id)
        warnings.append("Cleanup permanently deletes listed resources and messages. Rollback cannot restore them.")

    if schema.get("server_name"):
        rendered = _style_text(schema["server_name"], schema.get("server_font"))
        if rendered != guild.name:
            steps.append(PlanStep("update", "server", rendered, "server_name", guild.id))
    for i, data in enumerate(schema["roles"]):
        path = f"roles[{i}]"
        name = _styled_name(data, schema.get("role_font"))
        try:
            existing = resolve_role(guild, data, schema.get("role_font"), selected_roles,
                                    skip_existing_roles, excluded)
        except ValueError as exc:
            errors.append(str(exc))
            existing = None
        wanted = _resolve_permissions(data.get("permissions", []))
        if existing is not None:
            steps.append(PlanStep("reuse", "role", existing.name, path, existing.id))
            if existing.managed or existing.is_default() or existing >= me.top_role:
                errors.append(f"Cannot use {existing.name!r}: choose an unmanaged role below Damu's highest role.")
            if wanted.value & ~existing.permissions.value and not existing.permissions.administrator:
                warnings.append(f"Reused role {existing.name!r} has different permissions; it will not be edited.")
            if schema.get("auto_assign") == data["name"]:
                if any(getattr(existing.permissions, flag) for flag in DANGEROUS_PERMISSIONS):
                    errors.append(f"Auto-assign role {existing.name!r} already has privileged permissions.")
        else:
            steps.append(PlanStep("create", "role", name, path))
            if not permissions.administrator and wanted.value & ~permissions.value:
                errors.append(f"Role {name!r} requests permissions Damu does not have.")
        dangerous = DANGEROUS_PERMISSIONS.intersection(data.get("permissions", []))
        if dangerous:
            warnings.append(f"Role {name!r} has privileged permissions: {', '.join(sorted(dangerous))}.")

    global_font = schema.get("font") or schema.get("name_font") or schema.get("name_style")
    overwrites = 0
    existing_categories = {c.name for c in guild.categories if c.id not in deleted_channels}
    existing_names = {c.name for c in guild.channels if c.id not in deleted_channels}
    for i, category in enumerate(schema["categories"]):
        path = f"categories[{i}]"
        name = _styled_name(category, schema.get("category_font") or global_font)
        steps.append(PlanStep("create", "category", name, path))
        if name in existing_categories:
            warnings.append(f"Category {name!r} exists; a new category will be created, not merged.")
        overwrites += len(category.get("permission_overwrites", []))
        for j, channel in enumerate(category.get("channels", [])):
            ch_path = f"{path}.channels[{j}]"
            name = _styled_name(channel, schema.get("channel_font") or global_font)
            steps.append(PlanStep("create", "channel", name, ch_path))
            if name in existing_names:
                warnings.append(f"Channel {name!r} exists; a new channel will be created, not updated.")
            overwrites += len(channel.get("permission_overwrites", []))
            if channel["type"] == "forum" and "COMMUNITY" not in guild.features:
                errors.append(f"{ch_path}: forum creation requires Community enabled on this server.")
            if channel["type"] == "voice" and channel.get("bitrate", 64000) > guild.bitrate_limit:
                warnings.append(f"{name!r}: bitrate will be capped at {int(guild.bitrate_limit)}.")
            for k, thread in enumerate(channel.get("threads", [])):
                steps.append(PlanStep("create", "thread", thread["name"], f"{ch_path}.threads[{k}]"))
                if not permissions.create_private_threads:
                    errors.append("Damu needs Create Private Threads for configured threads.")
    if overwrites and not permissions.manage_roles:
        errors.append("Damu needs Manage Roles to apply channel permission overwrites.")
    for kind, limit, current in (("role", 250, len(guild.roles)), ("category", 50, len(guild.categories))):
        total = current + sum(s.resource == kind and s.action == "create" for s in steps)
        total -= sum(s.resource == kind and s.action == "delete" for s in steps)
        if total > limit:
            errors.append(f"Build would exceed Discord's {limit} {kind} limit ({total}).")
    total = len(guild.channels) - len(deleted_channels)
    total += sum(s.action == "create" and s.resource in {"category", "channel"} for s in steps)
    if total > 500:
        errors.append(f"Build would exceed Discord's 500 total channel limit ({total}).")
    if schema.get("verification", {}).get("enabled"):
        warnings.append("Verification runs after the resource build; its extra resources are not included in these counts.")
    return BuildPlan(config, tuple(steps), tuple(warnings), tuple(dict.fromkeys(errors)), overwrites)
