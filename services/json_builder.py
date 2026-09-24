"""JSON server builder — creates roles, categories, channels from a schema dict."""

from __future__ import annotations

import logging
from typing import Any

import discord

log = logging.getLogger("services.json_builder")

# ── Permission name → discord.Permissions flag mapping ────────────────────
_PERM_MAP: dict[str, int] = {
    "administrator": discord.Permissions.administrator.flag,
    "manage_guild": discord.Permissions.manage_guild.flag,
    "manage_channels": discord.Permissions.manage_channels.flag,
    "manage_roles": discord.Permissions.manage_roles.flag,
    "manage_messages": discord.Permissions.manage_messages.flag,
    "manage_threads": discord.Permissions.manage_threads.flag,
    "kick_members": discord.Permissions.kick_members.flag,
    "ban_members": discord.Permissions.ban_members.flag,
    "send_messages": discord.Permissions.send_messages.flag,
    "view_channel": discord.Permissions.view_channel.flag,
    "read_messages": discord.Permissions.read_messages.flag,
    "read_message_history": discord.Permissions.read_message_history.flag,
    "create_public_threads": discord.Permissions.create_public_threads.flag,
    "create_private_threads": discord.Permissions.create_private_threads.flag,
    "send_messages_in_threads": discord.Permissions.send_messages_in_threads.flag,
    "add_reactions": discord.Permissions.add_reactions.flag,
    "use_external_emojis": discord.Permissions.use_external_emojis.flag,
    "use_external_stickers": discord.Permissions.use_external_stickers.flag,
    "use_application_commands": discord.Permissions.use_application_commands.flag,
    "connect": discord.Permissions.connect.flag,
    "speak": discord.Permissions.speak.flag,
    "mute_members": discord.Permissions.mute_members.flag,
    "deafen_members": discord.Permissions.deafen_members.flag,
    "move_members": discord.Permissions.move_members.flag,
    "manage_nicknames": discord.Permissions.manage_nicknames.flag,
    "mention_everyone": discord.Permissions.mention_everyone.flag,
    "embed_links": discord.Permissions.embed_links.flag,
    "attach_files": discord.Permissions.attach_files.flag,
    "manage_webhooks": discord.Permissions.manage_webhooks.flag,
    "view_audit_log": discord.Permissions.view_audit_log.flag,
}


def _resolve_permissions(perm_names: list[str]) -> discord.Permissions:
    """Convert a list of permission name strings to a ``discord.Permissions`` object."""
    value = 0
    for name in perm_names:
        flag = _PERM_MAP.get(name.lower())
        if flag:
            value |= flag
        else:
            log.warning("Unknown permission name: %s", name)
    return discord.Permissions(value)


# ── Named colour presets ──────────────────────────────────────────────────────
_NAMED_COLOURS: dict[str, int] = {
    "red": 0xE74C3C, "dark_red": 0x992D22, "crimson": 0xDC143C,
    "orange": 0xE67E22, "dark_orange": 0xA84300,
    "yellow": 0xF1C40F, "gold": 0xFFD700, "amber": 0xFFBF00,
    "green": 0x2ECC71, "dark_green": 0x1F8B4C, "lime": 0x00FF00, "emerald": 0x50C878,
    "teal": 0x1ABC9C, "dark_teal": 0x11806A, "cyan": 0x00FFFF, "aqua": 0x00FFFF,
    "blue": 0x3498DB, "dark_blue": 0x206694, "navy": 0x000080, "royal_blue": 0x4169E1,
    "purple": 0x9B59B6, "dark_purple": 0x71368A, "violet": 0x8B00FF, "indigo": 0x4B0082,
    "magenta": 0xE91E63, "pink": 0xFFC0CB, "hot_pink": 0xFF69B4, "fuchsia": 0xFF00FF,
    "white": 0xFFFFFF, "light_grey": 0x95A5A6, "grey": 0x7F8C8D, "dark_grey": 0x546E7A,
    "black": 0x010101, "blurple": 0x5865F2, "greyple": 0x99AAB5,
}

_FONT_OFFSETS: dict[str, dict[str, int]] = {
    "bold": {"upper": 0x1D400, "lower": 0x1D41A, "digit": 0x1D7CE},
    "italic": {"upper": 0x1D434, "lower": 0x1D44E},
    "bold_italic": {"upper": 0x1D468, "lower": 0x1D482},
    "script": {"upper": 0x1D49C, "lower": 0x1D4B6},
    "bold_script": {"upper": 0x1D4D0, "lower": 0x1D4EA},
    "fraktur": {"upper": 0x1D504, "lower": 0x1D51E},
    "double_struck": {"upper": 0x1D538, "lower": 0x1D552, "digit": 0x1D7D8},
    "monospace": {"upper": 0x1D670, "lower": 0x1D68A, "digit": 0x1D7F6},
}

_SCRIPT_EXCEPTIONS = {
    "B": "\u212c", "E": "\u2130", "F": "\u2131", "H": "\u210b", "I": "\u2110",
    "L": "\u2112", "M": "\u2133", "R": "\u211b", "e": "\u212f", "g": "\u210a",
    "o": "\u2134",
}
_FRAKTUR_EXCEPTIONS = {
    "C": "\u212d", "H": "\u210c", "I": "\u2111", "R": "\u211c", "Z": "\u2128",
}
_DOUBLE_STRUCK_EXCEPTIONS = {
    "C": "\u2102", "H": "\u210d", "N": "\u2115", "P": "\u2119", "Q": "\u211a",
    "R": "\u211d", "Z": "\u2124",
}
_SMALL_CAPS = str.maketrans({
    "a": "\u1d00", "b": "\u0299", "c": "\u1d04", "d": "\u1d05", "e": "\u1d07",
    "f": "\ua730", "g": "\u0262", "h": "\u029c", "i": "\u026a", "j": "\u1d0a",
    "k": "\u1d0b", "l": "\u029f", "m": "\u1d0d", "n": "\u0274", "o": "\u1d0f",
    "p": "\u1d18", "q": "q", "r": "\u0280", "s": "s", "t": "\u1d1b",
    "u": "\u1d1c", "v": "\u1d20", "w": "\u1d21", "x": "x", "y": "\u028f",
    "z": "\u1d22",
})


def _parse_colour(colour_str: str | None) -> discord.Colour:
    """Parse a colour from hex (#FF0000) or named colour (red, gold, blurple, etc.)."""
    if not colour_str:
        return discord.Colour.default()
    cleaned = colour_str.strip().lower().replace(" ", "_").replace("-", "_")
    # Check named colours first
    if cleaned in _NAMED_COLOURS:
        return discord.Colour(_NAMED_COLOURS[cleaned])
    # Then try hex
    try:
        return discord.Colour(int(cleaned.lstrip("#"), 16))
    except ValueError:
        log.warning("Unknown colour: %s — using default", colour_str)
        return discord.Colour.default()


def _style_text(text: str, style: str | None) -> str:
    """Apply a Unicode text style. Discord does not support installable fonts."""
    if not style:
        return text

    normalized = style.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "small_caps":
        return text.lower().translate(_SMALL_CAPS)

    offsets = _FONT_OFFSETS.get(normalized)
    if not offsets:
        return text

    exceptions: dict[str, str] = {}
    if normalized in {"script", "bold_script"}:
        exceptions = _SCRIPT_EXCEPTIONS
    elif normalized == "fraktur":
        exceptions = _FRAKTUR_EXCEPTIONS
    elif normalized == "double_struck":
        exceptions = _DOUBLE_STRUCK_EXCEPTIONS

    styled: list[str] = []
    for char in text:
        if char in exceptions:
            styled.append(exceptions[char])
        elif "A" <= char <= "Z" and "upper" in offsets:
            styled.append(chr(offsets["upper"] + ord(char) - ord("A")))
        elif "a" <= char <= "z" and "lower" in offsets:
            styled.append(chr(offsets["lower"] + ord(char) - ord("a")))
        elif "0" <= char <= "9" and "digit" in offsets:
            styled.append(chr(offsets["digit"] + ord(char) - ord("0")))
        else:
            styled.append(char)

    return "".join(styled)


def _styled_name(data: dict[str, Any], fallback_style: str | None = None) -> str:
    style = data.get("font") or data.get("name_font") or data.get("name_style") or fallback_style
    return _style_text(data["name"], style)


def _role_aliases(role_name: str) -> set[str]:
    lowered = role_name.lower()
    aliases = {role_name}
    if any(word in lowered for word in ("owner", "admin", "administrator")):
        aliases.update({"Owner", "Admin", "Administrator"})
    if any(word in lowered for word in ("mod", "moderator")):
        aliases.update({"Mod", "Moderator"})
    return aliases


def _find_existing_role(guild: discord.Guild, name: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=name)


def _forum_sort_order(value: str | None) -> discord.ForumOrderType | None:
    if not value:
        return None
    cleaned = value.lower().replace("-", "_").replace(" ", "_")
    return {
        "latest_activity": discord.ForumOrderType.latest_activity,
        "creation_date": discord.ForumOrderType.creation_date,
    }.get(cleaned)


def _forum_layout(value: str | None) -> discord.ForumLayoutType | None:
    if not value:
        return None
    cleaned = value.lower().replace("-", "_").replace(" ", "_")
    return {
        "not_set": discord.ForumLayoutType.not_set,
        "list": discord.ForumLayoutType.list_view,
        "list_view": discord.ForumLayoutType.list_view,
        "gallery": discord.ForumLayoutType.gallery_view,
        "gallery_view": discord.ForumLayoutType.gallery_view,
    }.get(cleaned)


def _forum_tags(tags: list[dict[str, Any]]) -> list[discord.ForumTag]:
    forum_tags: list[discord.ForumTag] = []
    for tag in tags[:20]:
        emoji = tag.get("emoji")
        forum_tags.append(
            discord.ForumTag(
                name=tag["name"],
                emoji=emoji if isinstance(emoji, str) else None,
                moderated=tag.get("moderated", False),
            )
        )
    return forum_tags


class BuildProgress:
    """Simple progress tracker that can update an embed message."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.done = 0

    def advance(self) -> None:
        self.done += 1

    @property
    def bar(self) -> str:
        filled = int((self.done / max(self.total, 1)) * 20)
        return "\u2588" * filled + "\u2591" * (20 - filled) + f" {self.done}/{self.total}"


async def build_server(
    guild: discord.Guild,
    schema: dict[str, Any],
    progress_msg: discord.Message | None = None,
    selected_roles: dict[str, discord.Role] | None = None,
    skip_existing_roles: bool = True,
) -> tuple[list[str], dict[str, discord.Role]]:
    """Build roles, categories, and channels in *guild* from *schema*.

    Returns ``(logs, role_map)`` where *logs* is a list of description lines
    and *role_map* maps role-name \u2192 created :class:`discord.Role`.
    Raises on fatal errors after rolling-back partially created objects.
    """
    created_roles: list[discord.Role] = []
    created_channels: list[discord.abc.GuildChannel] = []
    logs: list[str] = []

    # Count total items for progress
    total = len(schema.get("roles", [])) + sum(
        1 + len(cat.get("channels", [])) for cat in schema.get("categories", [])
    )
    progress = BuildProgress(total)

    try:
        # ── Rename server ────────────────────────────────────────────────────
        global_font = schema.get("font") or schema.get("name_font") or schema.get("name_style")
        channel_font = schema.get("channel_font") or global_font
        category_font = schema.get("category_font") or global_font
        role_font = schema.get("role_font")

        if schema.get("server_name"):
            server_name = _style_text(schema["server_name"], schema.get("server_font"))
            await guild.edit(name=server_name)
            logs.append(f"Renamed server to **{server_name}**")

        # ── Create roles ─────────────────────────────────────────────────────
        role_map: dict[str, discord.Role] = {}
        for alias, role in (selected_roles or {}).items():
            role_map[alias] = role
            for extra_alias in _role_aliases(alias):
                role_map.setdefault(extra_alias, role)

        for role_data in schema.get("roles", []):
            role_name = role_data["name"]
            styled_role_name = _styled_name(role_data, role_font)
            role_permissions = [perm.lower() for perm in role_data.get("permissions", [])]

            existing_role = role_map.get(role_name)
            if not existing_role and selected_roles:
                if "administrator" in role_permissions:
                    existing_role = selected_roles.get("Admin") or selected_roles.get("Administrator")
                elif any(word in role_name.lower() for word in ("mod", "moderator")):
                    existing_role = selected_roles.get("Mod") or selected_roles.get("Moderator")

            if not existing_role and skip_existing_roles:
                existing_role = _find_existing_role(guild, role_name) or _find_existing_role(guild, styled_role_name)

            if existing_role:
                role_map[role_name] = existing_role
                role_map[styled_role_name] = existing_role
                for alias in _role_aliases(role_name):
                    role_map.setdefault(alias, existing_role)
                logs.append(f"Skipped existing role: **{existing_role.name}**")
                progress.advance()
                if progress_msg:
                    await _update_progress(progress_msg, progress)
                continue

            perms = _resolve_permissions(role_data.get("permissions", []))
            colour = _parse_colour(role_data.get("color"))
            role = await guild.create_role(
                name=styled_role_name,
                colour=colour,
                hoist=role_data.get("hoist", False),
                mentionable=role_data.get("mentionable", False),
                permissions=perms,
            )
            created_roles.append(role)
            role_map[role_name] = role
            role_map[styled_role_name] = role
            for alias in _role_aliases(role_name):
                role_map.setdefault(alias, role)
            logs.append(f"Created role: **{role.name}**")
            progress.advance()
            if progress_msg:
                await _update_progress(progress_msg, progress)

        # ── Create categories + channels ─────────────────────────────────────
        for cat_data in schema.get("categories", []):
            # Build permission overwrites for category
            overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
            for ow in cat_data.get("permission_overwrites", []):
                role_name = ow.get("role", "")
                target_role = role_map.get(role_name)
                if not target_role and role_name.lower() == "@everyone":
                    target_role = guild.default_role
                if target_role:
                    allow = _resolve_permissions(ow.get("allow", []))
                    deny = _resolve_permissions(ow.get("deny", []))
                    overwrites[target_role] = discord.PermissionOverwrite.from_pair(allow, deny)

            category_name = _styled_name(cat_data, category_font)
            category = await guild.create_category(name=category_name, overwrites=overwrites)
            created_channels.append(category)
            logs.append(f"Created category: **{category_name}**")
            progress.advance()
            if progress_msg:
                await _update_progress(progress_msg, progress)

            for ch_data in cat_data.get("channels", []):
                # ── Per-channel permission overwrites ────────────────────────
                ch_overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
                for ow in ch_data.get("permission_overwrites", []):
                    target = role_map.get(ow.get("role", ""))
                    if not target and ow.get("role", "").lower() == "@everyone":
                        target = guild.default_role
                    if target:
                        allow = _resolve_permissions(ow.get("allow", []))
                        deny = _resolve_permissions(ow.get("deny", []))
                        ch_overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)

                ch_type = ch_data.get("type", "text").lower()
                channel_name = _styled_name(ch_data, channel_font)
                if ch_type == "voice":
                    # Clamp bitrate to guild's max (96000 for unboosted servers)
                    max_bitrate = guild.bitrate_limit
                    bitrate = min(ch_data.get("bitrate", 64000), max_bitrate)
                    kwargs: dict[str, Any] = {
                        "name": channel_name,
                        "category": category,
                        "bitrate": bitrate,
                        "user_limit": ch_data.get("user_limit", 0),
                    }
                    if ch_overwrites:
                        kwargs["overwrites"] = ch_overwrites
                    vc = await guild.create_voice_channel(**kwargs)
                    created_channels.append(vc)
                    perm_note = f" (perms: {', '.join(o.get('role','') for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created voice channel: **{channel_name}**{perm_note}")
                elif ch_type == "forum":
                    kwargs = {
                        "name": channel_name,
                        "category": category,
                        "topic": ch_data.get("topic", ""),
                        "nsfw": ch_data.get("nsfw", False),
                        "slowmode_delay": ch_data.get("slowmode", 0),
                        "default_thread_slowmode_delay": ch_data.get("thread_slowmode", 0),
                        "default_auto_archive_duration": ch_data.get("auto_archive", 1440),
                    }
                    tags = _forum_tags(ch_data.get("tags", []))
                    if tags:
                        kwargs["available_tags"] = tags
                    sort_order = _forum_sort_order(ch_data.get("default_sort_order"))
                    if sort_order:
                        kwargs["default_sort_order"] = sort_order
                    layout = _forum_layout(ch_data.get("default_layout"))
                    if layout:
                        kwargs["default_layout"] = layout
                    if ch_data.get("default_reaction_emoji"):
                        kwargs["default_reaction_emoji"] = ch_data["default_reaction_emoji"]
                    if ch_overwrites:
                        kwargs["overwrites"] = ch_overwrites
                    forum = await guild.create_forum(**kwargs)
                    created_channels.append(forum)
                    perm_note = f" (perms: {', '.join(o.get('role','') for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created forum channel: **{channel_name}**{perm_note}")
                else:
                    kwargs: dict[str, Any] = {
                        "name": channel_name,
                        "category": category,
                        "topic": ch_data.get("topic", ""),
                        "slowmode_delay": ch_data.get("slowmode", 0),
                        "nsfw": ch_data.get("nsfw", False),
                    }
                    if ch_overwrites:
                        kwargs["overwrites"] = ch_overwrites
                    tc = await guild.create_text_channel(**kwargs)
                    created_channels.append(tc)
                    perm_note = f" (perms: {', '.join(o.get('role','') for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created text channel: **#{channel_name}**{perm_note}")

                    # Optional thread creation
                    for thread_data in ch_data.get("threads", []):
                        await tc.create_thread(
                            name=thread_data["name"],
                            auto_archive_duration=thread_data.get("auto_archive", 1440),
                        )
                        logs.append(f"  \u2514 Created thread: **{thread_data['name']}**")

                progress.advance()
                if progress_msg:
                    await _update_progress(progress_msg, progress)

    except Exception as exc:
        log.error("Build failed, rolling back: %s", exc)
        # Rollback
        for ch in reversed(created_channels):
            try:
                await ch.delete(reason="Server build rollback")
            except Exception:
                pass
        for role in reversed(created_roles):
            try:
                await role.delete(reason="Server build rollback")
            except Exception:
                pass
        raise

    return logs, role_map


_last_progress_update: float = 0.0


async def _update_progress(msg: discord.Message, progress: BuildProgress) -> None:
    """Edit the progress message embed, throttled to once every 2s to avoid rate limits."""
    import time
    import discord as _d
    global _last_progress_update
    now = time.monotonic()
    # Only update every 2 seconds or on completion to avoid Discord rate limits
    if now - _last_progress_update < 2.0 and progress.done < progress.total:
        return
    _last_progress_update = now
    em = _d.Embed(title="\U0001f528 Building Server\u2026", description=progress.bar, colour=0x5865F2)
    try:
        await msg.edit(embed=em)
    except discord.HTTPException:
        pass
