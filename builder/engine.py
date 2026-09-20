"""Discord resource executor, extracted from the legacy JSON service."""
from __future__ import annotations
import logging
from typing import Any
import discord
from builder.names import _parse_colour, _style_text, _styled_name
from builder.permissions import _resolve_permissions
from builder.progress import BuildProgress, _update_progress

log = logging.getLogger(__name__)

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


