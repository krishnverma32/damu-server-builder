"""Builder Executor — Executes full server build schemas with progress reporting."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import discord

from core.errors import DamuError
from core.models import Action, ActionStatus, BuildPlan, EngineResult
from engines.builder.rollback import BuilderRollback
from services.json_builder import _parse_colour, _resolve_permissions, _style_text

log = logging.getLogger("engines.builder.executor")


class BuilderExecutor:
    """Executes server plans with live progress throttled reporting and automatic rollback on error."""

    def __init__(self) -> None:
        self.rollback_engine = BuilderRollback()

    async def execute_plan(
        self,
        guild: discord.Guild,
        plan: BuildPlan,
        progress_message: discord.Message | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> EngineResult:
        created_channels: list[discord.abc.GuildChannel] = []
        created_roles: list[discord.Role] = []
        total = len(plan.actions)
        completed = 0
        last_update = 0.0

        schema = plan.metadata.get("schema", {})
        global_font = schema.get("font") or schema.get("name_font") or schema.get("name_style")
        channel_font = schema.get("channel_font") or global_font
        category_font = schema.get("category_font") or global_font
        role_font = schema.get("role_font")

        role_map: dict[str, discord.Role] = {}

        try:
            # Execute actions
            for action in plan.actions:
                action.status = ActionStatus.RUNNING

                # 1. Guild rename
                if action.parameters.get("action") == "rename_guild":
                    new_name = _style_text(action.parameters["name"], schema.get("server_font"))
                    await guild.edit(name=new_name)
                    action.status = ActionStatus.COMPLETED

                # 2. Role creation
                elif action.type.value == "create_role":
                    role_data = action.parameters
                    styled_name = _style_text(role_data["name"], role_data.get("font") or role_font)
                    perms = _resolve_permissions(role_data.get("permissions", []))
                    colour = _parse_colour(role_data.get("color"))

                    role = await guild.create_role(
                        name=styled_name,
                        colour=colour,
                        hoist=role_data.get("hoist", False),
                        mentionable=role_data.get("mentionable", False),
                        permissions=perms,
                        reason=f"DAMU Build {plan.build_id}",
                    )
                    created_roles.append(role)
                    action.created_resource_id = role.id
                    role_map[role_data["name"]] = role
                    role_map[styled_name] = role
                    action.status = ActionStatus.COMPLETED

                # 3. Category creation
                elif action.type.value == "create_category":
                    cat_data = action.parameters
                    cat_name = _style_text(cat_data["name"], cat_data.get("font") or category_font)

                    # Category overwrites
                    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
                    for ow in cat_data.get("permission_overwrites", []):
                        r_name = ow.get("role", "")
                        target = role_map.get(r_name) or (guild.default_role if r_name.lower() == "@everyone" else None)
                        if target:
                            allow = _resolve_permissions(ow.get("allow", []))
                            deny = _resolve_permissions(ow.get("deny", []))
                            overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)

                    cat = await guild.create_category(
                        name=cat_name,
                        overwrites=overwrites,
                        reason=f"DAMU Build {plan.build_id}",
                    )
                    created_channels.append(cat)
                    action.created_resource_id = cat.id
                    action.status = ActionStatus.COMPLETED

                # 4. Channel creation
                elif action.type.value == "create_channel":
                    ch_data = action.parameters
                    ch_type = ch_data.get("type", "text").lower()
                    ch_name = _style_text(ch_data["name"], ch_data.get("font") or channel_font)

                    # Find parent category
                    category: discord.CategoryChannel | None = None
                    cat_target = ch_data.get("category_target")
                    if cat_target:
                        styled_cat_name = _style_text(cat_target, category_font)
                        category = discord.utils.find(
                            lambda c: c.name in (cat_target, styled_cat_name),
                            guild.categories,
                        )

                    # Channel overwrites
                    ch_overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
                    for ow in ch_data.get("permission_overwrites", []):
                        r_name = ow.get("role", "")
                        target = role_map.get(r_name) or (guild.default_role if r_name.lower() == "@everyone" else None)
                        if target:
                            allow = _resolve_permissions(ow.get("allow", []))
                            deny = _resolve_permissions(ow.get("deny", []))
                            ch_overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)

                    if ch_type == "voice":
                        max_bitrate = guild.bitrate_limit
                        bitrate = min(ch_data.get("bitrate", 64000), max_bitrate)
                        vc = await guild.create_voice_channel(
                            name=ch_name,
                            category=category,
                            bitrate=bitrate,
                            user_limit=ch_data.get("user_limit", 0),
                            overwrites=ch_overwrites or None,
                            reason=f"DAMU Build {plan.build_id}",
                        )
                        created_channels.append(vc)
                        action.created_resource_id = vc.id
                    elif ch_type == "forum":
                        forum = await guild.create_forum(
                            name=ch_name,
                            category=category,
                            topic=ch_data.get("topic", ""),
                            nsfw=ch_data.get("nsfw", False),
                            slowmode_delay=ch_data.get("slowmode", 0),
                            overwrites=ch_overwrites or None,
                            reason=f"DAMU Build {plan.build_id}",
                        )
                        created_channels.append(forum)
                        action.created_resource_id = forum.id
                    else:
                        tc = await guild.create_text_channel(
                            name=ch_name,
                            category=category,
                            topic=ch_data.get("topic", ""),
                            slowmode_delay=ch_data.get("slowmode", 0),
                            nsfw=ch_data.get("nsfw", False),
                            overwrites=ch_overwrites or None,
                            reason=f"DAMU Build {plan.build_id}",
                        )
                        created_channels.append(tc)
                        action.created_resource_id = tc.id

                    action.status = ActionStatus.COMPLETED

                completed += 1
                now = time.monotonic()
                if (now - last_update >= 2.0 or completed == total) and progress_message:
                    last_update = now
                    bar_filled = int((completed / max(total, 1)) * 15)
                    bar = "█" * bar_filled + "░" * (15 - bar_filled)
                    progress_embed = discord.Embed(
                        title="🔨 Building Server...",
                        description=f"[{bar}] {completed}/{total}\nCurrent: **{action.target}**",
                        colour=0x5865F2,
                    )
                    try:
                        await progress_message.edit(embed=progress_embed)
                    except discord.HTTPException:
                        pass

                if on_progress:
                    on_progress(completed, total, action.target)

            return EngineResult.ok(
                operation=plan.operation,
                message=f"Server build '{plan.build_id}' finished successfully with {completed} actions.",
                actions=plan.actions,
                build_id=plan.build_id,
            )

        except Exception as exc:
            log.error("Server build failed for plan %s: %s. Rolling back.", plan.build_id, exc, exc_info=True)
            rollback_msg = await self.rollback_engine.rollback(created_channels, created_roles, plan.build_id)
            for a in plan.actions:
                if a.status == ActionStatus.RUNNING:
                    a.status = ActionStatus.FAILED
                    a.error = str(exc)

            return EngineResult.fail(
                operation=plan.operation,
                message=f"Build failed: {exc}",
                recovery=rollback_msg,
                build_id=plan.build_id,
                actions=plan.actions,
            )


builder_executor = BuilderExecutor()
