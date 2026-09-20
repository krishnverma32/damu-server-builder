"""Bounded JSON parsing, formal validation, and semantic configuration checks."""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import discord
from jsonschema import Draft202012Validator

from builder.exceptions import ConfigurationError
from builder.names import _styled_name
from builder.permissions import _resolve_permissions

MAX_CONFIG_BYTES = 1024 * 1024
DANGEROUS_PERMISSIONS = {
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "kick_members", "ban_members", "mention_everyone", "manage_webhooks",
}


@lru_cache(maxsize=1)
def schema_validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parent.parent / "schemas/server.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigurationError([f"Duplicate JSON key: {key[:100]}"])
        value[key] = item
    return value


def parse_json(raw: str) -> dict[str, Any]:
    """Accept JSON or one fenced JSON block, not arbitrary text surrounding JSON."""
    if len(raw.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ConfigurationError(["Configuration must be 1 MiB or smaller."])
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ConfigurationError(["Invalid JSON. Check syntax and nesting."]) from exc
    return validate_config(value)


def validate_config(raw: Any) -> dict[str, Any]:
    """Return an independent, normalized config; never silently discard settings."""
    try:
        if len(json.dumps(raw).encode("utf-8")) > MAX_CONFIG_BYTES:
            raise ConfigurationError(["Configuration must be 1 MiB or smaller."])
        errors = list(schema_validator().iter_errors(raw))
    except (RecursionError, TypeError, OverflowError) as exc:
        raise ConfigurationError(["Configuration must contain bounded JSON data."]) from exc
    if errors:
        issues = []
        for error in errors[:25]:
            path = "".join(f"[{part}]" if isinstance(part, int) else f".{part}"
                           for part in error.absolute_path).lstrip(".") or "config"
            # Do not echo entire rejected objects into Discord embeds.
            issues.append(f"{path}: {error.message[:200]}")
        raise ConfigurationError(issues)
    data = deepcopy(raw)
    data.setdefault("schema_version", "2.0")
    data.setdefault("roles", [])
    data.setdefault("categories", [])
    issues = []
    role_names: set[str] = set()
    styled_roles: set[str] = set()
    for i, role in enumerate(data["roles"]):
        name = role["name"]
        styled = _styled_name(role, data.get("role_font"))
        if name == "@everyone" or name in role_names or styled in styled_roles:
            issues.append(f"roles[{i}].name: duplicate or reserved role name {name!r}.")
        role_names.add(name)
        styled_roles.add(styled)
    roles = {role["name"]: role for role in data["roles"]}
    auto = data.get("auto_assign")
    if auto and auto not in role_names:
        issues.append("auto_assign: role must be declared in roles.")
    if auto in roles and DANGEROUS_PERMISSIONS.intersection(roles[auto].get("permissions", [])):
        issues.append("auto_assign: privileged roles cannot be assigned to all members.")

    categories: set[str] = set()
    global_font = data.get("font") or data.get("name_font") or data.get("name_style")
    channel_font = data.get("channel_font") or global_font
    category_font = data.get("category_font") or global_font
    for i, category in enumerate(data["categories"]):
        cat_path = f"categories[{i}]"
        name = _styled_name(category, category_font)
        if name in categories:
            issues.append(f"{cat_path}.name: duplicate rendered category name.")
        categories.add(name)
        _check_overwrites(category, cat_path, role_names, issues)
        channels: set[str] = set()
        for j, channel in enumerate(category.get("channels", [])):
            path = f"{cat_path}.channels[{j}]"
            channel.setdefault("type", "text")
            kind = channel["type"]
            name = _styled_name(channel, channel_font)
            if name in channels:
                issues.append(f"{path}.name: duplicate rendered channel name in category.")
            channels.add(name)
            _check_overwrites(channel, path, role_names, issues)
            allowed = {"name", "type", "font", "name_font", "name_style", "permission_overwrites"}
            if kind in ("voice", "stage"):
                allowed |= {"bitrate", "user_limit", "topic"}
            elif kind in ("text", "announcement"):
                allowed |= {"topic", "slowmode", "nsfw", "threads"}
                if len(channel.get("topic", "")) > 1024:
                    issues.append(f"{path}.topic: text topics must be at most 1024 characters.")
            elif kind == "forum":
                allowed |= {"topic", "slowmode", "nsfw", "thread_slowmode", "auto_archive",
                            "tags", "default_sort_order", "default_layout", "default_reaction_emoji"}
                tags = [tag["name"] for tag in channel.get("tags", [])]
                if len(tags) != len(set(tags)):
                    issues.append(f"{path}.tags: tag names must be unique.")
            for field in channel.keys() - allowed:
                issues.append(f"{path}.{field}: not supported for {kind} channels.")
    if issues:
        raise ConfigurationError(issues)
    return data


def _check_overwrites(data: dict[str, Any], path: str, roles: set[str], issues: list[str]) -> None:
    seen: set[str] = set()
    for i, overwrite in enumerate(data.get("permission_overwrites", [])):
        location = f"{path}.permission_overwrites[{i}]"
        target_role = overwrite.get("role")
        target_member = overwrite.get("member")
        if target_role:
            if target_role not in roles and target_role != "@everyone":
                issues.append(f"{location}.role: declare {target_role!r} in roles first.")
            target = f"role:{target_role}"
        elif target_member:
            target = f"member:{target_member}"
        else:
            issues.append(f"{location}: overwrite must specify either 'role' or 'member'.")
            continue

        if target in seen:
            issues.append(f"{location}: duplicate overwrite target {target!r}.")
        seen.add(target)
        allow = _resolve_permissions(overwrite.get("allow", []))
        deny = _resolve_permissions(overwrite.get("deny", []))
        if allow.value & deny.value:
            issues.append(f"{location}: the same permission cannot be allowed and denied (including aliases).")
        channel_flags = discord.Permissions.all_channel().value
        if (allow.value | deny.value) & ~channel_flags:
            issues.append(f"{location}: only channel permissions can be used in overwrites.")
