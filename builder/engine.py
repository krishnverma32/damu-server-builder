"""Discord resource executor, extracted from the legacy JSON service."""
from __future__ import annotations
import logging
from typing import Any
import discord
from builder.names import _parse_colour, _style_text, _styled_name
from builder.permissions import _resolve_permissions
from builder.progress import BuildProgress, _update_progress
from builder.models import BuildPlan, ServerConfig
from builder.planner import plan_build, resolve_role
from builder.rollback import rollback_created

log = logging.getLogger(__name__)

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


def _resolve_target(
    guild: discord.Guild,
    role_map: dict[str, discord.Role],
    ow: dict[str, Any],
) -> discord.Role | discord.Member | None:
    """Resolve an overwrite target to a discord.Role or discord.Member."""
    if "role" in ow:
        role_name = str(ow.get("role", ""))
        if role_name.lower() == "@everyone":
            return guild.default_role
        if role_name in role_map:
            return role_map[role_name]
        return discord.utils.get(guild.roles, name=role_name)
    if "member" in ow:
        member_ref = str(ow.get("member", "")).strip()
        if member_ref.isdigit():
            member = guild.get_member(int(member_ref))
            if member:
                return member
        return discord.utils.get(guild.members, name=member_ref)
    return None


async def build_server(
    guild: discord.Guild,
    schema: dict[str, Any],
    progress_msg: discord.Message | None = None,
    selected_roles: dict[str, discord.Role] | None = None,
    skip_existing_roles: bool = True,
    build_id: int | None = None,
    build_repo: Any | None = None,
) -> tuple[list[str], dict[str, discord.Role]]:
    """Build roles, categories, and channels in *guild* from *schema*.

    Returns ``(logs, role_map)`` where *logs* is a list of description lines
    and *role_map* maps role-name → created :class:`discord.Role`.
    Raises on fatal errors after rolling-back partially created objects.
    """
    config = ServerConfig.from_dict(schema)
    plan = plan_build(guild, config, selected_roles=selected_roles,
                      skip_existing_roles=skip_existing_roles)
    plan.require_valid()
    schema = config.to_dict()
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

        for role_data in schema.get("roles", []):
            role_name = role_data["name"]
            styled_role_name = _styled_name(role_data, role_font)

            existing_role = resolve_role(
                guild, role_data, role_font, selected_roles or {}, skip_existing_roles
            )

            if existing_role:
                role_map[role_name] = existing_role
                role_map[styled_role_name] = existing_role
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
            logs.append(f"Created role: **{role.name}**")
            progress.advance()
            if progress_msg:
                await _update_progress(progress_msg, progress)

        # ── Create categories + channels ─────────────────────────────────────
        for cat_data in schema.get("categories", []):
            # Build permission overwrites for category
            overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
            for ow in cat_data.get("permission_overwrites", []):
                target = _resolve_target(guild, role_map, ow)
                if target:
                    allow = _resolve_permissions(ow.get("allow", []))
                    deny = _resolve_permissions(ow.get("deny", []))
                    overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)

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
                    target = _resolve_target(guild, role_map, ow)
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
                    if "permission_overwrites" in ch_data:
                        kwargs["overwrites"] = ch_overwrites
                    vc = await guild.create_voice_channel(**kwargs)
                    created_channels.append(vc)
                    perm_note = f" (perms: {', '.join(str(o.get('role') or o.get('member')) for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created voice channel: **{channel_name}**{perm_note}")
                elif ch_type == "stage":
                    max_bitrate = guild.bitrate_limit
                    bitrate = min(ch_data.get("bitrate", 64000), max_bitrate)
                    kwargs = {
                        "name": channel_name,
                        "category": category,
                        "topic": ch_data.get("topic", ""),
                        "bitrate": bitrate,
                        "user_limit": ch_data.get("user_limit", 0),
                    }
                    if "permission_overwrites" in ch_data:
                        kwargs["overwrites"] = ch_overwrites
                    sc = await guild.create_stage_channel(**kwargs)
                    created_channels.append(sc)
                    perm_note = f" (perms: {', '.join(str(o.get('role') or o.get('member')) for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created stage channel: **{channel_name}**{perm_note}")
                elif ch_type in ("announcement", "news"):
                    is_news = "COMMUNITY" in guild.features
                    kwargs = {
                        "name": channel_name,
                        "category": category,
                        "topic": ch_data.get("topic", ""),
                        "slowmode_delay": ch_data.get("slowmode", 0),
                        "nsfw": ch_data.get("nsfw", False),
                    }
                    if is_news:
                        kwargs["news"] = True
                    if "permission_overwrites" in ch_data:
                        kwargs["overwrites"] = ch_overwrites
                    ac = await guild.create_text_channel(**kwargs)
                    created_channels.append(ac)
                    label = "announcement" if is_news else "text (community off)"
                    perm_note = f" (perms: {', '.join(str(o.get('role') or o.get('member')) for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created {label} channel: **#{channel_name}**{perm_note}")
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
                    if "permission_overwrites" in ch_data:
                        kwargs["overwrites"] = ch_overwrites
                    forum = await guild.create_forum(**kwargs)
                    created_channels.append(forum)
                    perm_note = f" (perms: {', '.join(str(o.get('role') or o.get('member')) for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created forum channel: **{channel_name}**{perm_note}")
                else:
                    kwargs = {
                        "name": channel_name,
                        "category": category,
                        "topic": ch_data.get("topic", ""),
                        "slowmode_delay": ch_data.get("slowmode", 0),
                        "nsfw": ch_data.get("nsfw", False),
                    }
                    if "permission_overwrites" in ch_data:
                        kwargs["overwrites"] = ch_overwrites
                    tc = await guild.create_text_channel(**kwargs)
                    created_channels.append(tc)
                    perm_note = f" (perms: {', '.join(str(o.get('role') or o.get('member')) for o in ch_data.get('permission_overwrites', []))})" if ch_overwrites else ""
                    logs.append(f"Created text channel: **#{channel_name}**{perm_note}")

                    # Optional thread creation
                    for thread_data in ch_data.get("threads", []):
                        await tc.create_thread(
                            name=thread_data["name"],
                            auto_archive_duration=thread_data.get("auto_archive", 1440),
                        )
                        logs.append(f"  └ Created thread: **{thread_data['name']}**")

                progress.advance()
                if progress_msg:
                    await _update_progress(progress_msg, progress)

        if build_repo and build_id:
            all_created_ids = [r.id for r in created_roles] + [c.id for c in created_channels]
            await build_repo.complete_build(
                build_id=build_id,
                status="completed",
                created_resources=all_created_ids,
            )

    except Exception as exc:
        log.error("Build failed, rolling back: %s", exc)
        failed = await rollback_created(created_channels, created_roles)
        if failed:
            log.error("Build rollback incomplete; manual cleanup required for IDs: %s", failed)
        if build_repo and build_id:
            await build_repo.complete_build(
                build_id=build_id,
                status="failed",
                errors=[str(exc)],
            )
        raise

    return logs, role_map



async def clean_resources(guild: discord.Guild, plan: BuildPlan) -> None:
    """Delete only the inventory explicitly reviewed by the administrator.

    Cleanup is irreversible. Stop on the first failure rather than silently
    continuing with a partially cleaned guild.
    """
    for step in plan.steps:
        if step.action != "delete" or step.resource_id is None:
            continue
        resource = (guild.get_role(step.resource_id) if step.resource == "role"
                    else guild.get_channel(step.resource_id))
        if resource is not None:
            await resource.delete(reason="Damu: explicitly confirmed destructive build")
