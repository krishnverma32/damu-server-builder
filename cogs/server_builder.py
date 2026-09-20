"""Server builder cog — /setup_server, /setup_custom, /server_json, /generate_server."""

from __future__ import annotations

import io
import json
import logging
import pathlib

import discord
from discord import app_commands
from discord.ext import commands

import config
from services import ai_service
from services.embed_service import error_embed, info_embed, success_embed
from builder.engine import build_server, clean_resources
from builder.exceptions import ConfigurationError
from builder.models import BuildPlan, ServerConfig
from builder.planner import plan_build
from builder.validator import MAX_CONFIG_BYTES
from builder.views import BuildConfirmView
from builder.permissions import _resolve_permissions
from builder.names import _style_text
from builder.templates import load_template, load_templates

log = logging.getLogger("cogs.server_builder")

MAX_SERVER_ICON_BYTES = 10 * 1024 * 1024
BYPASS_FILE = pathlib.Path(config.DATA_DIR) / "server_builder_bypass.json"
LAST_SCHEMA_FILE = pathlib.Path(config.DATA_DIR) / "server_builder_last_schema.json"


class BuildApprovalView(discord.ui.View):
    """Owner approval buttons for non-owner server build requests."""

    def __init__(self, owner_id: int, timeout: float = 600.0) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.approved: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True

        await interaction.response.send_message(
            "Only the configured build owner can answer this request.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Approve Build", style=discord.ButtonStyle.success)
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.approved = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Approved. The requester can continue.",
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.approved = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Denied. The server build will not run.",
            view=self,
        )
        self.stop()


class JsonPasteModal(discord.ui.Modal, title="Paste Server JSON"):
    """Large text box for pasted server JSON."""

    json_text = discord.ui.TextInput(
        label="Server JSON",
        placeholder='Paste JSON here, starting with { and ending with }',
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000,
    )

    def __init__(
        self,
        cog: "ServerBuilderCog",
        clean_existing: bool,
        selected_roles: dict[str, discord.Role],
        enable_verification: bool,
        perm_sync_after_build: bool,
    ) -> None:
        super().__init__()
        self.cog = cog
        self.clean_existing = clean_existing
        self.selected_roles = selected_roles
        self.enable_verification = enable_verification
        self.perm_sync_after_build = perm_sync_after_build

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            schema = self.cog._parse_server_schema(str(self.json_text))
        except ValueError as exc:
            return await interaction.response.send_message(
                embed=error_embed("Invalid JSON", str(exc)),
                ephemeral=True,
            )

        await self.cog._run_custom_schema_setup(
            interaction=interaction,
            schema=schema,
            clean_existing=self.clean_existing,
            server_icon=None,
            selected_roles=self.selected_roles,
            title="Last Check: Pasted JSON Server",
            reason_prefix="Pasted JSON setup",
            enable_verification=self.enable_verification,
            perm_sync_after_build=self.perm_sync_after_build,
        )

# ── Preset server templates ──────────────────────────────────────────────────────
TEMPLATES = load_templates()

TEMPLATE_CHOICES = [
    app_commands.Choice(name="Gaming Server", value="gaming"),
    app_commands.Choice(name="Community Server", value="community"),
    app_commands.Choice(name="Study Group", value="study"),
    app_commands.Choice(name="Business / Team", value="business"),
]

TEMPLATE_DETAILS: dict[str, dict[str, str]] = {
    "gaming": {
        "name": "Gaming Server",
        "summary": "A complete gaming community layout with game chat, media, LFG, music, VIP voice, and staff moderation areas.",
        "best_for": "Gaming clans, stream communities, esports groups, and casual multiplayer servers.",
    },
    "community": {
        "name": "Community Server",
        "summary": "A broad social community layout with introductions, media sharing, polls, suggestions, creative channels, voice rooms, and staff tools.",
        "best_for": "Creators, friend groups, fan communities, and public Discord communities.",
    },
    "study": {
        "name": "Study Group",
        "summary": "A learning-focused layout with resources, questions, homework help, subject channels, tutor permissions, and focused voice rooms.",
        "best_for": "School groups, coaching servers, coding study groups, and education communities.",
    },
    "business": {
        "name": "Business / Team",
        "summary": "A professional workspace layout with company notices, tasks, reports, departments, meeting rooms, and private management areas.",
        "best_for": "Teams, startups, agencies, internal workspaces, and project groups.",
    },
}

DETAILED_EXAMPLE_TEMPLATE = load_template("example")

_GENERATION_PROMPT = (
    "Generate a structured JSON object for a Discord server with the theme: '{theme}'.\n"
    "The JSON MUST follow this exact schema:\n"
    '{{\n'
    '  "server_name": "string",\n'
    '  "roles": [\n'
    '    {{ "name": "string", "color": "named_color_or_#HEX", "hoist": bool, "mentionable": bool, '
    '"permissions": ["permission_name"] }}\n'
    '  ],\n'
    '  "categories": [\n'
    '    {{\n'
    '      "name": "string",\n'
    '      "permission_overwrites": [\n'
    '        {{ "role": "RoleName_or_@everyone", "allow": ["perm"], "deny": ["perm"] }}\n'
    '      ],\n'
    '      "channels": [\n'
    '        {{ "type": "text", "name": "string", "topic": "string", "slowmode": 0, "nsfw": false,\n'
    '           "permission_overwrites": [\n'
    '             {{ "role": "RoleName", "allow": ["send_messages"], "deny": [] }}\n'
    '           ]\n'
    '        }},\n'
    '        {{ "type": "voice", "name": "string", "bitrate": 64000, "user_limit": 0 }},\n'
    '        {{ "type": "forum", "name": "string", "topic": "string", "tags": [{{ "name": "Question", "emoji": "❓" }}] }}\n'
    '      ]\n'
    '    }}\n'
    '  ],\n'
    '  "auto_assign": "Member"\n'
    '}}\n'
    "IMPORTANT RULES:\n"
    "- For role colors use named colors: red, gold, blue, green, purple, magenta, crimson, emerald, teal, orange, pink, grey, blurple (or #HEX)\n"
    "- Both categories AND individual channels can have permission_overwrites\n"
    "- Use '@everyone' as role name in overwrites to target the default role\n"
    "- INFO/announcement channels: deny send_messages for @everyone, allow only for Admin/Mod\n"
    "- Staff categories: deny read_messages for @everyone, allow only for staff roles\n"
    "- Use type 'forum' for Discord forum channels when the theme needs posts/discussions\n"
    "- Optional verification object: {{\"enabled\": true, \"embed_title\": \"Verify To Enter\", \"embed_description\": \"...\", \"button_text\": \"Verify\", \"account_age_check\": false, \"min_account_age_days\": 7}}\n"
    "- Optional name styling keys: font, name_font, name_style. Supported: bold, italic, bold_italic, script, bold_script, fraktur, double_struck, monospace, small_caps\n"
    "- Keep bitrate at 64000-96000 (no higher)\n"
    "Return ONLY valid JSON, no explanation."
)


class ServerBuilderCog(commands.Cog, name="Server Builder"):
    """Server generation — AI-powered or from preset templates."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Keep the same guard across cog reloads; release on cancellation/errors.
        if not hasattr(bot, "_damu_active_builds"):
            bot._damu_active_builds = set()
        self._active_builds = bot._damu_active_builds

    @staticmethod
    def _count_schema_items(schema: dict) -> tuple[int, int, int]:
        roles = len(schema.get("roles", []))
        categories = len(schema.get("categories", []))
        channels = sum(len(cat.get("channels", [])) for cat in schema.get("categories", []))
        return roles, categories, channels

    @staticmethod
    def _format_overwrites(overwrites: list[dict]) -> str:
        if not overwrites:
            return "none"

        parts: list[str] = []
        for overwrite in overwrites[:8]:
            role = overwrite.get("role", "unknown")
            allow = ", ".join(overwrite.get("allow", [])) or "none"
            deny = ", ".join(overwrite.get("deny", [])) or "none"
            parts.append(f"{role}: allow [{allow}], deny [{deny}]")

        if len(overwrites) > 8:
            parts.append(f"...and {len(overwrites) - 8} more")

        return "; ".join(parts)

    @staticmethod
    def _schema_style(schema: dict, kind: str) -> str | None:
        global_font = schema.get("font") or schema.get("name_font") or schema.get("name_style")
        return schema.get(f"{kind}_font") or global_font

    @staticmethod
    def _styled_schema_name(data: dict, fallback_style: str | None = None) -> str:
        style = data.get("font") or data.get("name_font") or data.get("name_style") or fallback_style
        return _style_text(data.get("name", ""), style)

    @staticmethod
    def _perm_names_missing(actual: discord.Permissions, expected_names: list[str]) -> list[str]:
        expected = _resolve_permissions(expected_names)
        missing: list[str] = []
        for name in expected_names:
            flag = getattr(discord.Permissions, name.lower(), None)
            if flag is None:
                continue
            value = flag.flag
            if expected.value & value and not actual.value & value:
                missing.append(name)
        return missing

    def _load_last_schema(self, guild_id: int) -> dict | None:
        try:
            if not LAST_SCHEMA_FILE.exists():
                return None
            data = json.loads(LAST_SCHEMA_FILE.read_text(encoding="utf-8"))
            schema = data.get(str(guild_id))
            return schema if isinstance(schema, dict) else None
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def _save_last_schema(self, guild_id: int, schema: dict) -> None:
        try:
            LAST_SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if LAST_SCHEMA_FILE.exists():
                data = json.loads(LAST_SCHEMA_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            data[str(guild_id)] = schema
            LAST_SCHEMA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, json.JSONDecodeError, TypeError):
            log.warning("Could not save last server schema for guild %s", guild_id)

    def _resolve_schema_role(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        role_name: str,
        role_style: str | None,
    ) -> discord.Role | None:
        if role_name.lower() == "@everyone":
            return guild.default_role
        if role_name in role_map:
            return role_map[role_name]
        styled_name = _style_text(role_name, role_style)
        role = discord.utils.get(guild.roles, name=role_name) or discord.utils.get(guild.roles, name=styled_name)
        if role:
            role_map[role_name] = role
            role_map[styled_name] = role
        return role

    async def _audit_schema_permissions(self, guild: discord.Guild, schema: dict) -> tuple[bool, list[str]]:
        issues: list[str] = []
        role_style = self._schema_style(schema, "role")
        category_style = self._schema_style(schema, "category")
        channel_style = self._schema_style(schema, "channel")
        role_map: dict[str, discord.Role] = {}

        for role_data in schema.get("roles", []):
            role_name = role_data.get("name")
            if not role_name:
                continue
            styled_name = self._styled_schema_name(role_data, role_style)
            role = discord.utils.get(guild.roles, name=role_name) or discord.utils.get(guild.roles, name=styled_name)
            if not role:
                issues.append(f"Missing role: `{role_name}`")
                continue
            role_map[role_name] = role
            role_map[styled_name] = role
            missing = self._perm_names_missing(role.permissions, role_data.get("permissions", []))
            if missing:
                issues.append(f"Role `{role.name}` missing permissions: {', '.join(missing)}")

        for cat_data in schema.get("categories", []):
            category_name = self._styled_schema_name(cat_data, category_style)
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                issues.append(f"Missing category: `{cat_data.get('name', 'unnamed')}`")
                continue

            self._audit_overwrites(guild, category, cat_data.get("permission_overwrites", []), role_map, role_style, issues)

            for ch_data in cat_data.get("channels", []):
                channel_name = self._styled_schema_name(ch_data, channel_style)
                channel = discord.utils.get(category.channels, name=channel_name)
                if not channel:
                    issues.append(f"Missing channel: `{channel_name}` in `{category.name}`")
                    continue
                expected_type = ch_data.get("type", "text").lower()
                if expected_type == "voice" and not isinstance(channel, discord.VoiceChannel):
                    issues.append(f"Channel `{channel.name}` should be voice.")
                elif expected_type == "forum" and not isinstance(channel, discord.ForumChannel):
                    issues.append(f"Channel `{channel.name}` should be forum.")
                elif expected_type not in {"voice", "forum"} and not isinstance(channel, discord.TextChannel):
                    issues.append(f"Channel `{channel.name}` should be text.")
                self._audit_overwrites(guild, channel, ch_data.get("permission_overwrites", []), role_map, role_style, issues)

        return not issues, issues

    def _audit_overwrites(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        overwrites: list[dict],
        role_map: dict[str, discord.Role],
        role_style: str | None,
        issues: list[str],
    ) -> None:
        for overwrite in overwrites:
            role_name = overwrite.get("role", "")
            target = self._resolve_schema_role(guild, role_map, role_name, role_style)
            if not target:
                issues.append(f"`{channel.name}` overwrite target missing: `{role_name}`")
                continue
            actual = channel.overwrites_for(target)
            allow, deny = actual.pair()
            missing_allow = self._perm_names_missing(allow, overwrite.get("allow", []))
            missing_deny = self._perm_names_missing(deny, overwrite.get("deny", []))
            if missing_allow:
                issues.append(f"`{channel.name}` missing allow for `{target.name}`: {', '.join(missing_allow)}")
            if missing_deny:
                issues.append(f"`{channel.name}` missing deny for `{target.name}`: {', '.join(missing_deny)}")

    async def _dm_perm_sync_result(
        self,
        guild: discord.Guild,
        schema: dict,
        ok: bool,
        issues: list[str],
        context: str,
    ) -> None:
        owner = guild.owner or await self.bot.fetch_user(guild.owner_id)
        roles, categories, text_channels, voice_channels, forum_channels = self._template_counts(schema)
        base = [
            f"Server: **{guild.name}** (`{guild.id}`)",
            f"Owner: <@{guild.owner_id}>",
            f"Members: **{guild.member_count or 0}**",
            f"JSON expected: **{roles}** roles, **{categories}** categories, **{text_channels}** text, **{voice_channels}** voice, **{forum_channels}** forum",
            f"Actual: **{len(guild.roles)}** roles, **{len(guild.categories)}** categories, **{len(guild.text_channels)}** text, **{len(guild.voice_channels)}** voice, **{len(guild.forums)}** forums",
        ]
        if ok:
            embed = success_embed("Perm Sync OK OK", "\n".join(base + [f"Context: **{context}**", "Permissions match the JSON checks."]))
        else:
            shown = "\n".join(f"- {issue}" for issue in issues[:20])
            extra = f"\n...and {len(issues) - 20} more issues." if len(issues) > 20 else ""
            embed = error_embed(
                "Perm Sync Issues Found",
                "\n".join(base + [f"Context: **{context}**", "", shown + extra]),
            )
        try:
            await owner.send(embed=embed)
        except discord.HTTPException:
            log.warning("Could not DM permission sync result to guild owner %s", guild.owner_id)

    async def _run_perm_sync_report(
        self,
        guild: discord.Guild,
        schema: dict,
        context: str,
        *,
        dm_owner: bool = True,
    ) -> tuple[bool, list[str], str]:
        ok, issues = await self._audit_schema_permissions(guild, schema)
        if dm_owner:
            await self._dm_perm_sync_result(guild, schema, ok, issues, context)
        if ok:
            return True, issues, "Perm Sync OK OK. Server permissions match the JSON checks."
        shown = "\n".join(f"- {issue}" for issue in issues[:12])
        if len(issues) > 12:
            shown += f"\n...and {len(issues) - 12} more issues."
        return False, issues, f"Perm sync found problems. Check JSON vs actual server:\n{shown}"

    @staticmethod
    def _template_counts(schema: dict) -> tuple[int, int, int, int, int]:
        roles = len(schema.get("roles", []))
        categories = len(schema.get("categories", []))
        text_channels = 0
        voice_channels = 0
        forum_channels = 0
        for category in schema.get("categories", []):
            for channel in category.get("channels", []):
                channel_type = channel.get("type", "text").lower()
                if channel_type == "voice":
                    voice_channels += 1
                elif channel_type == "forum":
                    forum_channels += 1
                else:
                    text_channels += 1
        return roles, categories, text_channels, voice_channels, forum_channels

    def _template_detail_text(self, key: str, schema: dict) -> str:
        metadata = TEMPLATE_DETAILS.get(key, {})
        roles, categories, text_channels, voice_channels, forum_channels = self._template_counts(schema)
        lines = [
            f"Template: {metadata.get('name', key.title())}",
            metadata.get("summary", "Ready-to-build server template."),
            "",
            f"Best for: {metadata.get('best_for', 'General Discord servers.')}",
            f"Creates: {roles} roles, {categories} categories, {text_channels} text channels, {voice_channels} voice channels, {forum_channels} forum channels",
            f"Auto-assign role: {schema.get('auto_assign') or 'none'}",
            "",
            "Roles:",
        ]

        for role in schema.get("roles", []):
            perms = ", ".join(role.get("permissions", [])) or "none"
            lines.append(
                f"- {role.get('name', 'unnamed')} | color {role.get('color', 'default')} | perms: {perms}"
            )

        lines.extend(["", "Categories and channels:"])
        for category in schema.get("categories", []):
            cat_overwrites = self._format_overwrites(category.get("permission_overwrites", []))
            lines.append(f"- {category.get('name', 'unnamed category')} | perms: {cat_overwrites}")
            for channel in category.get("channels", []):
                channel_type = channel.get("type", "text")
                topic = channel.get("topic") or "No topic"
                overwrites = self._format_overwrites(channel.get("permission_overwrites", []))
                lines.append(
                    f"  - [{channel_type}] {channel.get('name', 'unnamed-channel')} | {topic} | perms: {overwrites}"
                )

        return "\n".join(lines)

    async def _read_server_icon(
        self,
        server_icon: discord.Attachment | None,
    ) -> bytes | None:
        if not server_icon:
            return None

        content_type = (server_icon.content_type or "").lower()
        filename = server_icon.filename.lower()
        allowed_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        if not content_type.startswith("image/") and not filename.endswith(allowed_ext):
            raise ValueError("Please upload an image file for the server icon.")

        if server_icon.size and server_icon.size > MAX_SERVER_ICON_BYTES:
            raise ValueError("Server icon image must be 10 MB or smaller.")

        icon_bytes = await server_icon.read()
        if len(icon_bytes) > MAX_SERVER_ICON_BYTES:
            raise ValueError("Server icon image must be 10 MB or smaller.")

        return icon_bytes

    async def _confirm_schema_before_build(
        self, interaction: discord.Interaction, title: str, schema: dict,
        clean_existing: bool, server_icon: discord.Attachment | None = None,
        selected_roles: dict[str, discord.Role] | None = None,
        enable_verification: bool = False,
    ) -> BuildPlan | None:
        guild = interaction.guild
        if guild is None:
            return None
        try:
            config_model = ServerConfig.from_dict(schema)
            plan = plan_build(guild, config_model, selected_roles=selected_roles,
                              clean_existing=clean_existing, safe_channel_id=interaction.channel_id)
            plan.require_valid()
            if server_icon and not guild.me.guild_permissions.manage_guild:
                raise ConfigurationError(["Damu needs Manage Server to update the server icon."])
        except ConfigurationError as exc:
            await interaction.followup.send(embed=error_embed("Build blocked", str(exc)), ephemeral=True)
            return None
        extra = ("\nServer icon: will update" if server_icon else "")
        extra += f"\nVerification after build: {'enabled' if enable_verification else 'disabled'}"
        embed = info_embed(title, plan.summary() + extra)
        embed.set_footer(text="Review both files. Cleanup requires typing CONFIRM DELETE and cannot be undone.")
        files = [
            discord.File(io.BytesIO(json.dumps(config_model.to_dict(), indent=2).encode()),
                         filename="server_build_preview.json"),
            discord.File(io.BytesIO(json.dumps(plan.to_dict(), indent=2).encode()),
                         filename="server_build_plan.json"),
        ]
        view = BuildConfirmView(interaction.user.id, destructive=clean_existing)
        message = await interaction.followup.send(embed=embed, files=files, view=view, wait=True,
                                                 ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        await view.wait()
        if view.confirmed is True:
            current = plan_build(guild, config_model, selected_roles=selected_roles,
                                 clean_existing=clean_existing, safe_channel_id=interaction.channel_id)
            member = guild.get_member(interaction.user.id)
            if member is None or not member.guild_permissions.administrator:
                reason = "Your Administrator permission changed. Start a new setup."
            elif server_icon and not guild.me.guild_permissions.manage_guild:
                reason = "Damu lost Manage Server permission. Start a new setup."
            elif current.to_dict() != plan.to_dict():
                reason = "Server state or permissions changed during review. Start again for a fresh plan."
            else:
                await message.edit(embed=info_embed("Setup Confirmed", "Starting the reviewed build."),
                                   attachments=[], view=None)
                return current
        else:
            reason = "Setup cancelled." if view.confirmed is False else "Setup expired. Start a new setup."
        await message.edit(embed=error_embed("Setup Not Started", reason), attachments=[], view=None)
        return None

    async def _apply_server_icon(
        self,
        guild: discord.Guild,
        icon_bytes: bytes | None,
        reason: str,
    ) -> str | None:
        if not icon_bytes:
            return None

        await guild.edit(icon=icon_bytes, reason=reason)
        return "Updated server icon from uploaded image"

    @staticmethod
    def _selected_role_map(
        admin_role: discord.Role | None = None,
        mod_role: discord.Role | None = None,
    ) -> dict[str, discord.Role]:
        selected: dict[str, discord.Role] = {}
        if admin_role:
            selected.update({
                "Admin": admin_role,
                "Administrator": admin_role,
                "Owner": admin_role,
            })
        if mod_role:
            selected.update({
                "Mod": mod_role,
                "Moderator": mod_role,
            })
        return selected

    @staticmethod
    def _verification_enabled_from_schema(schema: dict, fallback: bool = False) -> bool:
        verification = schema.get("verification")
        if isinstance(verification, dict):
            return bool(verification.get("enabled", fallback))
        return fallback

    async def _setup_verification_after_build(
        self,
        guild: discord.Guild,
        schema: dict,
        enable_verification: bool,
    ) -> list[str]:
        if not enable_verification:
            return []

        verification_cog = self.bot.get_cog("Verification")
        if verification_cog is None or not hasattr(verification_cog, "setup_verification_system"):
            return ["Verification setup skipped: verification cog is not loaded."]

        verification = schema.get("verification") if isinstance(schema.get("verification"), dict) else {}
        title = verification.get("embed_title") or verification.get("title") or "Verify To Enter"
        description = (
            verification.get("embed_description")
            or verification.get("description")
            or "Welcome to **{server}**.\nRead the rules, then press the button below to unlock the community."
        )
        button_text = verification.get("button_text") or "Verify"
        account_age_check = bool(verification.get("account_age_check", False))
        min_account_age_days = int(verification.get("min_account_age_days", 7) or 0)

        try:
            _, setup_logs = await verification_cog.setup_verification_system(
                guild,
                auto_create=True,
                embed_title=title,
                embed_description=description,
                button_text=button_text,
                account_age_check=account_age_check,
                min_account_age_days=min_account_age_days,
            )
        except Exception as exc:
            log.exception("Verification setup failed after server build: %s", exc)
            return [f"Verification setup failed: `{exc}`"]

        logs = ["Verification system enabled with verify-here, Verified, and Unverified."]
        logs.extend(setup_logs)
        return logs

    @staticmethod
    def _load_build_bypass_ids() -> set[int]:
        ids = {config.SERVER_BUILD_OWNER_ID, *config.SERVER_BUILD_BYPASS_IDS}
        try:
            if BYPASS_FILE.exists():
                data = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))
                ids.update(int(item) for item in data.get("user_ids", []))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            log.warning("Could not read server builder bypass file.")
        return ids

    @staticmethod
    def _save_build_bypass_ids(user_ids: set[int]) -> None:
        BYPASS_FILE.parent.mkdir(parents=True, exist_ok=True)
        persisted = sorted(uid for uid in user_ids if uid != config.SERVER_BUILD_OWNER_ID)
        BYPASS_FILE.write_text(
            json.dumps({"user_ids": persisted}, indent=2),
            encoding="utf-8",
        )

    def _is_build_bypassed(self, guild: discord.Guild, user: discord.abc.User) -> bool:
        if user.id == guild.owner_id:
            return True
        return user.id in self._load_build_bypass_ids()

    async def _ensure_build_authorized(
        self,
        interaction: discord.Interaction,
        schema: dict,
        build_name: str,
    ) -> bool:
        if not interaction.guild:
            return False

        guild = interaction.guild
        if self._is_build_bypassed(guild, interaction.user):
            return True

        roles_count, categories_count, channels_count = self._count_schema_items(schema)
        requester = interaction.user
        owner = self.bot.get_user(config.SERVER_BUILD_OWNER_ID)
        if owner is None:
            try:
                owner = await self.bot.fetch_user(config.SERVER_BUILD_OWNER_ID)
            except discord.HTTPException:
                owner = None

        wait_embed = info_embed(
            "Waiting For Approval",
            "You are not the server owner or an approved bypass user.\n"
            "I sent the configured build owner a DM for permission. Please wait.",
        )
        await interaction.followup.send(embed=wait_embed, ephemeral=True)

        if owner is None:
            await interaction.followup.send(
                embed=error_embed(
                    "Approval Failed",
                    "I could not find the configured build owner to request permission.",
                ),
                ephemeral=True,
            )
            return False

        view = BuildApprovalView(config.SERVER_BUILD_OWNER_ID)
        approval_embed = info_embed(
            "Server Build Permission Request",
            (
                f"Requester: {requester.mention} (`{requester.id}`)\n"
                f"Server: **{guild.name}** (`{guild.id}`)\n"
                f"Build: **{build_name}**\n"
                f"Creates: **{roles_count}** roles, **{categories_count}** categories, "
                f"**{channels_count}** channels\n\n"
                "Approve to let this build continue, or deny to stop it."
            ),
        )

        try:
            dm_message = await owner.send(embed=approval_embed, view=view)
        except discord.HTTPException:
            await interaction.followup.send(
                embed=error_embed(
                    "Approval Failed",
                    "I could not DM the configured build owner. Build stopped.",
                ),
                ephemeral=True,
            )
            return False

        await view.wait()

        if view.approved is True:
            await interaction.followup.send(
                embed=success_embed("Approved", "Build owner approved this setup. Continuing..."),
                ephemeral=True,
            )
            return True

        if view.approved is False:
            await interaction.followup.send(
                embed=error_embed("Denied", "Build owner denied this server setup."),
                ephemeral=True,
            )
            return False

        for child in view.children:
            child.disabled = True
        try:
            await dm_message.edit(content="Approval timed out. The server build was stopped.", view=view)
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            embed=error_embed("Approval Timed Out", "Build owner did not approve in time."),
            ephemeral=True,
        )
        return False

    @staticmethod
    def _parse_server_schema(raw_json: str) -> dict:
        return ServerConfig.from_json(raw_json).to_dict()

    async def _run_custom_schema_setup(self, interaction: discord.Interaction, **kwargs) -> None:
        if interaction.guild is None:
            return
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("Administrator permission is required.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        if guild_id in self._active_builds:
            await interaction.followup.send("A build or review is already active for this server.", ephemeral=True)
            return
        self._active_builds.add(guild_id)
        try:
            kwargs["schema"] = ServerConfig.from_dict(kwargs["schema"]).to_dict()
            await self._execute_schema_setup(interaction=interaction, **kwargs)
        except ConfigurationError as exc:
            await interaction.followup.send(embed=error_embed("Invalid configuration", str(exc)), ephemeral=True)
        finally:
            self._active_builds.discard(guild_id)

    async def _execute_schema_setup(
        self,
        interaction: discord.Interaction,
        schema: dict,
        clean_existing: bool,
        server_icon: discord.Attachment | None,
        selected_roles: dict[str, discord.Role],
        title: str,
        reason_prefix: str,
        enable_verification: bool | None = None,
        perm_sync_after_build: bool = True,
    ) -> None:
        if not interaction.guild:
            return

        guild = interaction.guild
        verification_enabled = self._verification_enabled_from_schema(
            schema,
            bool(enable_verification),
        )

        authorized = await self._ensure_build_authorized(interaction, schema, title)
        if not authorized:
            return

        try:
            icon_bytes = await self._read_server_icon(server_icon)
        except ValueError as exc:
            return await interaction.followup.send(
                embed=error_embed("Invalid Server Icon", str(exc)),
                ephemeral=True,
            )

        confirmed = await self._confirm_schema_before_build(
            interaction,
            title,
            schema,
            clean_existing,
            server_icon,
            selected_roles,
            verification_enabled,
        )
        if not confirmed:
            return

        if clean_existing:
            try:
                await clean_resources(guild, confirmed)
            except discord.HTTPException:
                log.exception("Destructive cleanup interrupted in guild %s", guild.id)
                await interaction.followup.send(embed=error_embed(
                    "Cleanup interrupted", "Cleanup stopped after an API failure. Some resources may already be deleted. "
                    "Check Damu's permissions and the audit log before trying again."), ephemeral=True)
                return
        status_msg = None

        progress_em = info_embed("Building Server", "Starting...")
        if status_msg:
            try:
                await status_msg.edit(embed=progress_em)
            except discord.NotFound:
                status_msg = None
            progress_msg = status_msg or await interaction.followup.send(embed=progress_em, wait=True)
        else:
            progress_msg = await interaction.followup.send(embed=progress_em, wait=True)

        try:
            icon_log = await self._apply_server_icon(guild, icon_bytes, f"{reason_prefix} - uploaded icon")
            logs, role_map = await build_server(
                guild,
                schema,
                progress_msg,
                selected_roles=selected_roles,
            )
            if icon_log:
                logs.insert(0, icon_log)

            logs.extend(
                await self._setup_verification_after_build(
                    guild,
                    schema,
                    verification_enabled,
                )
            )
            self._save_last_schema(guild.id, schema)
            if perm_sync_after_build:
                ok, _, sync_text = await self._run_perm_sync_report(guild, schema, reason_prefix)
                logs.append("Perm Sync OK OK. Owner DM sent." if ok else sync_text)

            assign_logs: list[str] = []
            for r in schema.get("roles", []):
                if "administrator" in r.get("permissions", []):
                    if r["name"] in role_map:
                        try:
                            assert isinstance(interaction.user, discord.Member)
                            await interaction.user.add_roles(
                                role_map[r["name"]], reason=f"{reason_prefix} - owner"
                            )
                            assign_logs.append(
                                f"Assigned **{r['name']}** to {interaction.user.mention}"
                            )
                        except discord.HTTPException:
                            pass
                    break

            auto_role_name = schema.get("auto_assign")
            if auto_role_name and auto_role_name in role_map:
                default_role = role_map[auto_role_name]
                assigned = 0
                for member in guild.members:
                    if member.bot or member.id == interaction.user.id:
                        continue
                    try:
                        await member.add_roles(default_role, reason=f"{reason_prefix} - auto-assign")
                        assigned += 1
                    except discord.HTTPException:
                        pass
                if assigned:
                    assign_logs.append(
                        f"Assigned **{auto_role_name}** to **{assigned}** existing members"
                    )

            summary_sent, summary_failed = await self._post_created_channel_summaries(
                guild,
                schema,
                interaction.user.mention,
            )
            if summary_sent:
                assign_logs.append(f"Posted channel summary messages in **{summary_sent}** channels")
            if summary_failed:
                assign_logs.append(f"Skipped/failed channel summary messages in **{summary_failed}** channels")

            all_logs = logs + assign_logs
            result = "\n".join(all_logs) if all_logs else "Nothing was created."
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await progress_msg.edit(embed=success_embed("Custom Server Ready!", result))

        except Exception as exc:
            log.exception("Custom setup failed: %s", exc)
            em = error_embed(
                "Build Failed",
                "Build interrupted. Removal of newly created resources was attempted. "
                "Earlier deletions, server changes, and post-build actions are not restored. "
                "Check Damu's role/permissions and logs before retrying.",
            )
            await progress_msg.edit(embed=em)

    @staticmethod
    def _infer_channel_summary(channel_name: str, topic: str | None = None) -> str:
        if topic and topic.strip():
            return topic.strip()

        lowered = channel_name.lower()
        checks: list[tuple[tuple[str, ...], str]] = [
            (("rule",), "Read the server rules and important guidelines here."),
            (("announce", "news", "update"), "Official updates and important notices are posted here."),
            (("welcome", "intro"), "Welcome messages and introductions happen here."),
            (("bot", "cmd", "command"), "Use bot commands and automation features in this channel."),
            (("media", "gallery", "photo", "video", "art", "meme"), "Share images, videos, and media content here."),
            (("general", "chat", "talk"), "General discussion channel for day-to-day conversations."),
            (("support", "help", "question", "ticket"), "Ask questions and get support from staff and members here."),
            (("staff", "mod", "admin", "management"), "Private coordination channel for staff and moderation."),
            (("log", "audit"), "Server logs and moderation records are kept here."),
            (("voice", "lounge", "room", "meeting", "call"), "Join voice conversations and live discussions here."),
            (("music",), "Music sessions, listening parties, and music-related chat happen here."),
            (("study", "homework", "resource"), "Study resources, learning discussions, and academic help are shared here."),
        ]

        for keywords, summary in checks:
            if any(word in lowered for word in keywords):
                return summary

        return "Use this channel for discussions related to its name and category."

    async def _post_created_channel_summaries(
        self,
        guild: discord.Guild,
        schema: dict,
        actor_mention: str,
    ) -> tuple[int, int]:
        sent = 0
        failed = 0
        global_font = schema.get("font") or schema.get("name_font") or schema.get("name_style")
        channel_font = schema.get("channel_font") or global_font

        for cat in schema.get("categories", []):
            for ch_data in cat.get("channels", []):
                if ch_data.get("type", "text").lower() != "text":
                    continue

                channel_name = ch_data.get("name", "")
                if not channel_name:
                    continue

                styled_channel_name = _style_text(
                    channel_name,
                    ch_data.get("font")
                    or ch_data.get("name_font")
                    or ch_data.get("name_style")
                    or channel_font,
                )
                channel = discord.utils.get(guild.text_channels, name=styled_channel_name)
                if not channel:
                    failed += 1
                    continue

                if not channel.permissions_for(guild.me).send_messages:
                    failed += 1
                    continue

                summary = self._infer_channel_summary(channel_name, ch_data.get("topic"))
                msg = (
                    f"\U0001f44b Welcome to {channel.mention}!\n"
                    f"\U0001f4dd {summary}\n"
                    f"Created by {actor_mention}."
                )

                try:
                    await channel.send(msg)
                    sent += 1
                except discord.HTTPException:
                    failed += 1

        return sent, failed

    def _build_server_summary_lines(self, guild: discord.Guild) -> list[str]:
        lines: list[str] = []
        for category in guild.categories:
            text_channels = [
                ch
                for ch in guild.text_channels
                if ch.category_id == category.id
            ]
            for channel in text_channels:
                purpose = self._infer_channel_summary(channel.name, channel.topic)
                lines.append(f"{channel.mention} \u2014 {purpose}")

        uncategorized = [
            ch
            for ch in guild.text_channels
            if ch.category_id is None
        ]
        for channel in uncategorized:
            purpose = self._infer_channel_summary(channel.name, channel.topic)
            lines.append(f"{channel.mention} \u2014 {purpose}")

        return lines

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # /setup_server \u2014 preset template builder (NO AI needed)
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app_commands.command(
        name="setup_server",
        description="Auto-setup server with roles, channels, and categories from a template.",
    )
    @app_commands.describe(
        template="Choose a server template",
        clean_existing="Delete ALL existing channels/roles first (keeps command channel)",
        server_icon="Optional image to set as the server picture/icon",
        admin_role="Use an existing admin role instead of creating a new one",
        mod_role="Use an existing moderator role instead of creating a new one",
        enable_verification="Create a verification gate with Verified/Unverified roles",
        perm_sync_after_build="After build, check JSON roles/channel permissions and DM the owner",
    )
    @app_commands.choices(
        template=TEMPLATE_CHOICES
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_server(
        self,
        interaction: discord.Interaction,
        template: app_commands.Choice[str],
        clean_existing: bool = False,
        server_icon: discord.Attachment | None = None,
        admin_role: discord.Role | None = None,
        mod_role: discord.Role | None = None,
        enable_verification: bool = False,
        perm_sync_after_build: bool = True,
    ) -> None:
        if not interaction.guild:
            return

        template_schema = TEMPLATES.get(template.value)
        if not template_schema:
            return await interaction.response.send_message(
                embed=error_embed("Error", "Template not found."), ephemeral=True
            )
        schema = json.loads(json.dumps(template_schema))

        await self._run_custom_schema_setup(
            interaction=interaction, schema=schema, clean_existing=clean_existing,
            server_icon=server_icon, selected_roles=self._selected_role_map(admin_role, mod_role),
            title=f"Last Check: {template.name}", reason_prefix="Template setup",
            enable_verification=enable_verification, perm_sync_after_build=perm_sync_after_build,
        )

    @app_commands.command(
        name="server_templates",
        description="List all available server builder templates with detailed summaries.",
    )
    async def server_templates(self, interaction: discord.Interaction) -> None:
        lines = [
            "Use `/template_details` to inspect a template, `/server_json` to export JSON, or `/setup_server` to build.",
            "",
        ]

        for key, schema in TEMPLATES.items():
            metadata = TEMPLATE_DETAILS.get(key, {})
            roles, categories, text_channels, voice_channels, forum_channels = self._template_counts(schema)
            lines.extend([
                f"**{metadata.get('name', key.title())}** (`{key}`)",
                metadata.get("summary", "Ready-to-build server template."),
                f"Best for: {metadata.get('best_for', 'General Discord servers.')}",
                (
                    f"Includes: **{roles}** roles, **{categories}** categories, "
                    f"**{text_channels}** text, **{voice_channels}** voice, **{forum_channels}** forum channels"
                ),
                f"Auto role: **{schema.get('auto_assign') or 'none'}**",
                "",
            ])

        await interaction.response.send_message(
            embed=info_embed("Available Server Templates", "\n".join(lines)),
            ephemeral=True,
        )

    @app_commands.command(
        name="template_details",
        description="Show detailed roles, categories, channels, and permissions for one template.",
    )
    @app_commands.describe(template="Template to inspect in detail")
    @app_commands.choices(template=TEMPLATE_CHOICES)
    async def template_details(
        self,
        interaction: discord.Interaction,
        template: app_commands.Choice[str],
    ) -> None:
        schema = TEMPLATES.get(template.value)
        if not schema:
            return await interaction.response.send_message(
                embed=error_embed("Template Not Found", "That template does not exist."),
                ephemeral=True,
            )

        detail_text = self._template_detail_text(template.value, schema)
        metadata = TEMPLATE_DETAILS.get(template.value, {})
        title = f"{metadata.get('name', template.name)} Details"
        json_file = discord.File(
            io.BytesIO(json.dumps(schema, indent=2, ensure_ascii=False).encode("utf-8")),
            filename=f"server_template_{template.value}.json",
        )

        if len(detail_text) <= 3900:
            embed = info_embed(title, detail_text)
            embed.set_footer(text="Attached JSON can be edited and used with /setup_custom.")
            await interaction.response.send_message(embed=embed, file=json_file, ephemeral=True)
            return

        detail_file = discord.File(
            io.BytesIO(detail_text.encode("utf-8")),
            filename=f"server_template_{template.value}_details.txt",
        )
        embed = info_embed(
            title,
            "This template has a large layout, so I attached both the detailed breakdown and the JSON file.",
        )
        await interaction.response.send_message(
            embed=embed,
            files=[detail_file, json_file],
            ephemeral=True,
        )

    @app_commands.command(
        name="example_template",
        description="Get a detailed copy-ready example JSON template for /setup_custom.",
    )
    async def example_template(self, interaction: discord.Interaction) -> None:
        text = json.dumps(DETAILED_EXAMPLE_TEMPLATE, indent=2, ensure_ascii=False)
        file = discord.File(
            io.BytesIO(text.encode("utf-8")),
            filename="detailed_example_server_template.json",
        )
        roles, categories, text_channels, voice_channels, forum_channels = self._template_counts(
            DETAILED_EXAMPLE_TEMPLATE
        )
        embed = info_embed(
            "Detailed Example Template",
            (
                "Copy the attached JSON or upload it with `/setup_custom`.\n"
                f"Includes **{roles}** roles, **{categories}** categories, "
                f"**{text_channels}** text channels, **{voice_channels}** voice channels, "
                f"**{forum_channels}** forum channels, styled names, permissions, forum tags, "
                "and verification settings."
            ),
        )
        embed.set_footer(text="This is an editable example, not a required format.")
        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)

    @app_commands.command(
        name="server_json",
        description="Get the JSON schema/template you can use with /setup_custom.",
    )
    @app_commands.describe(
        template="Export a preset template as JSON, or leave blank for blank schema",
    )
    @app_commands.choices(
        template=[
            app_commands.Choice(name="Blank Schema (empty)", value="blank"),
            app_commands.Choice(name="Detailed Example", value="example"),
            *TEMPLATE_CHOICES,
        ]
    )
    async def server_json(
        self,
        interaction: discord.Interaction,
        template: app_commands.Choice[str] | None = None,
    ) -> None:
        choice = template.value if template else "blank"

        if choice == "blank":
            schema = {
                "server_name": "My Awesome Server",
                "roles": [
                    {
                        "name": "Admin",
                        "color": "red",
                        "hoist": True,
                        "mentionable": False,
                        "permissions": ["administrator"],
                    },
                    {
                        "name": "Moderator",
                        "color": "green",
                        "hoist": True,
                        "mentionable": True,
                        "permissions": [
                            "kick_members",
                            "ban_members",
                            "manage_messages",
                            "manage_channels",
                        ],
                    },
                    {
                        "name": "Member",
                        "color": "blue",
                        "hoist": False,
                        "mentionable": False,
                        "permissions": ["send_messages", "read_messages"],
                    },
                ],
                "categories": [
                    {
                        "name": "INFO",
                        "permission_overwrites": [
                            {
                                "role": "@everyone",
                                "allow": ["read_messages"],
                                "deny": ["send_messages"],
                            },
                            {
                                "role": "Admin",
                                "allow": ["send_messages"],
                                "deny": [],
                            },
                        ],
                        "channels": [
                            {
                                "type": "text",
                                "name": "rules",
                                "topic": "Server rules",
                                "slowmode": 0,
                                "nsfw": False,
                            },
                            {
                                "type": "text",
                                "name": "announcements",
                                "topic": "Important updates",
                                "permission_overwrites": [
                                    {
                                        "role": "Admin",
                                        "allow": ["send_messages", "mention_everyone"],
                                        "deny": [],
                                    },
                                    {
                                        "role": "Moderator",
                                        "allow": ["send_messages"],
                                        "deny": [],
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "name": "GENERAL",
                        "channels": [
                            {
                                "type": "text",
                                "name": "general-chat",
                                "topic": "Main chat",
                            },
                            {
                                "type": "voice",
                                "name": "Voice Chat",
                                "bitrate": 96000,
                                "user_limit": 0,
                            },
                        ],
                    },
                    {
                        "name": "STAFF ONLY",
                        "permission_overwrites": [
                            {
                                "role": "@everyone",
                                "allow": [],
                                "deny": ["read_messages"],
                            },
                            {
                                "role": "Moderator",
                                "allow": ["read_messages", "send_messages"],
                                "deny": [],
                            },
                            {
                                "role": "Admin",
                                "allow": ["read_messages", "send_messages"],
                                "deny": [],
                            },
                        ],
                        "channels": [
                            {
                                "type": "text",
                                "name": "staff-chat",
                                "topic": "Staff only",
                            },
                        ],
                    },
                ],
                "auto_assign": "Member",
                "verification": {
                    "enabled": True,
                    "embed_title": "Verify To Enter",
                    "embed_description": "Welcome to **{server}**.\nRead the rules, then press Verify to unlock the community.",
                    "button_text": "Verify",
                    "account_age_check": False,
                    "min_account_age_days": 7,
                },
            }
            title = "Server JSON Schema"
        elif choice == "example":
            schema = DETAILED_EXAMPLE_TEMPLATE
            title = "Detailed Example Template JSON"
        else:
            schema = TEMPLATES.get(choice)
            if not schema:
                return await interaction.response.send_message(
                    embed=error_embed("Error", "Template not found."), ephemeral=True
                )
            title = f"{template.name} Template JSON"  # type: ignore[union-attr]

        text = json.dumps(schema, indent=2, ensure_ascii=False)

        # If it fits in an embed, send it; otherwise send as a .json file
        if len(text) <= 4000:
            em = info_embed(title, f"```json\n{text}\n```")
            em.set_footer(text="Copy this JSON, edit it, and use /setup_custom to build!")
            await interaction.response.send_message(embed=em, ephemeral=True)
        else:
            # Send as attachment
            import io

            file = discord.File(
                io.BytesIO(text.encode("utf-8")),
                filename=f"server_template_{choice}.json",
            )
            em = info_embed(title, "Template is too large for embed \u2014 attached as file.\nEdit and use `/setup_custom` to build!")
            await interaction.response.send_message(embed=em, file=file, ephemeral=True)

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # /setup_paste_json \u2014 paste JSON into a modal text box
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app_commands.command(
        name="setup_paste_json",
        description="Open a large text box to paste server JSON, then preview and build.",
    )
    @app_commands.describe(
        clean_existing="Delete ALL existing channels/roles first (keeps command channel)",
        admin_role="Use an existing admin role instead of creating a new one",
        mod_role="Use an existing moderator role instead of creating a new one",
        enable_verification="Enable verification even if the pasted JSON does not include verification.enabled",
        perm_sync_after_build="After build, check JSON roles/channel permissions and DM the owner",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_paste_json(
        self,
        interaction: discord.Interaction,
        clean_existing: bool = False,
        admin_role: discord.Role | None = None,
        mod_role: discord.Role | None = None,
        enable_verification: bool = False,
        perm_sync_after_build: bool = True,
    ) -> None:
        selected_roles = self._selected_role_map(admin_role, mod_role)
        await interaction.response.send_modal(
            JsonPasteModal(
                cog=self,
                clean_existing=clean_existing,
                selected_roles=selected_roles,
                enable_verification=enable_verification,
                perm_sync_after_build=perm_sync_after_build,
            )
        )

    async def _require_build_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == config.SERVER_BUILD_OWNER_ID:
            return True

        await interaction.response.send_message(
            embed=error_embed(
                "Not Allowed",
                "Only the configured build owner can manage server-build bypass users.",
            ),
            ephemeral=True,
        )
        return False

    @app_commands.command(
        name="builder_bypass_add",
        description="Allow a user ID to build servers without DM approval.",
    )
    @app_commands.describe(user_id="Discord user ID to allow")
    async def builder_bypass_add(self, interaction: discord.Interaction, user_id: str) -> None:
        if not await self._require_build_owner(interaction):
            return

        try:
            uid = int(user_id.strip())
        except ValueError:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User ID", "Please provide a numeric Discord user ID."),
                ephemeral=True,
            )

        ids = self._load_build_bypass_ids()
        ids.add(uid)
        self._save_build_bypass_ids(ids)
        await interaction.response.send_message(
            embed=success_embed("Bypass Added", f"`{uid}` can now build without DM approval."),
            ephemeral=True,
        )

    @app_commands.command(
        name="builder_bypass_remove",
        description="Remove a user ID from server-build bypass.",
    )
    @app_commands.describe(user_id="Discord user ID to remove")
    async def builder_bypass_remove(self, interaction: discord.Interaction, user_id: str) -> None:
        if not await self._require_build_owner(interaction):
            return

        try:
            uid = int(user_id.strip())
        except ValueError:
            return await interaction.response.send_message(
                embed=error_embed("Invalid User ID", "Please provide a numeric Discord user ID."),
                ephemeral=True,
            )

        ids = self._load_build_bypass_ids()
        ids.discard(uid)
        self._save_build_bypass_ids(ids)
        await interaction.response.send_message(
            embed=success_embed("Bypass Removed", f"`{uid}` now needs DM approval again."),
            ephemeral=True,
        )

    @app_commands.command(
        name="builder_bypass_list",
        description="List users who can build servers without DM approval.",
    )
    async def builder_bypass_list(self, interaction: discord.Interaction) -> None:
        if not await self._require_build_owner(interaction):
            return

        ids = sorted(self._load_build_bypass_ids())
        text = "\n".join(f"- `{uid}`" for uid in ids) or "No bypass users configured."
        await interaction.response.send_message(
            embed=info_embed("Server Build Bypass Users", text),
            ephemeral=True,
        )

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # /setup_custom \u2014 build from user-provided JSON
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app_commands.command(
        name="setup_custom",
        description="Build a server from your own JSON template (paste or attach .json).",
    )
    @app_commands.describe(
        json_text="Paste your server JSON here (or attach a .json file)",
        json_file="Upload a .json file with your server template",
        enable_verification="Enable verification even if the JSON does not include verification.enabled",
        clean_existing="Delete ALL existing channels/roles first (keeps command channel)",
        server_icon="Optional image to set as the server picture/icon",
        admin_role="Use an existing admin role instead of creating a new one",
        mod_role="Use an existing moderator role instead of creating a new one",
        perm_sync_after_build="After build, check JSON roles/channel permissions and DM the owner",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_custom(
        self,
        interaction: discord.Interaction,
        json_text: str | None = None,
        json_file: discord.Attachment | None = None,
        clean_existing: bool = False,
        server_icon: discord.Attachment | None = None,
        admin_role: discord.Role | None = None,
        mod_role: discord.Role | None = None,
        enable_verification: bool = False,
        perm_sync_after_build: bool = True,
    ) -> None:
        if not interaction.guild:
            return

        # Get JSON from either text or file
        raw_json: str | None = None
        if json_file:
            if not json_file.filename.endswith(".json"):
                return await interaction.response.send_message(
                    embed=error_embed("Error", "Please upload a `.json` file."),
                    ephemeral=True,
                )
            if json_file.size > MAX_CONFIG_BYTES:
                return await interaction.response.send_message("JSON must be 1 MiB or smaller.", ephemeral=True)
            try:
                raw_json = (await json_file.read()).decode("utf-8-sig")
            except UnicodeDecodeError:
                return await interaction.response.send_message("Upload UTF-8 JSON text.", ephemeral=True)
        elif json_text:
            raw_json = json_text
        else:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Error",
                    "Provide either `json_text` or attach a `.json` file.\nUse `/server_json` to get the schema.",
                ),
                ephemeral=True,
            )

        try:
            schema = self._parse_server_schema(raw_json)
        except ValueError as exc:
            return await interaction.response.send_message(
                embed=error_embed("Invalid JSON", str(exc)),
                ephemeral=True,
            )

        selected_roles = self._selected_role_map(admin_role, mod_role)
        return await self._run_custom_schema_setup(
            interaction=interaction,
            schema=schema,
            clean_existing=clean_existing,
            server_icon=server_icon,
            selected_roles=selected_roles,
            title="Last Check: Custom Server",
            reason_prefix="Custom setup",
            enable_verification=enable_verification,
            perm_sync_after_build=perm_sync_after_build,
        )

    @app_commands.command(
        name="channel_summaries",
        description="Post a small summary of channel purposes in this chat.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def channel_summaries(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Error", "This command can only be used in a server."),
                ephemeral=True,
            )

        lines = self._build_server_summary_lines(interaction.guild)
        if not lines:
            return await interaction.response.send_message(
                embed=info_embed("Channel Summaries", "No text channels found to summarize."),
                ephemeral=True,
            )

        content = "\n".join(lines)
        if len(content) > 3900:
            content = content[:3900] + "\n..."

        em = info_embed("Channel Summaries", content)
        em.set_footer(text="These summaries are generated from channel topics/names.")
        await interaction.response.send_message(embed=em)

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # /generate_server \u2014 AI-powered server builder
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app_commands.command(
        name="perm_sync_check",
        description="Check current server roles/channel permissions against JSON or the last build.",
    )
    @app_commands.describe(
        template="Optional preset/example template to compare against",
        json_text="Optional pasted JSON to compare against",
        json_file="Optional uploaded .json file to compare against",
        dm_owner="Send the result to the server owner by DM",
    )
    @app_commands.choices(
        template=[
            app_commands.Choice(name="Last Build JSON", value="last"),
            app_commands.Choice(name="Detailed Example", value="example"),
            *TEMPLATE_CHOICES,
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def perm_sync_check(
        self,
        interaction: discord.Interaction,
        template: app_commands.Choice[str] | None = None,
        json_text: str | None = None,
        json_file: discord.Attachment | None = None,
        dm_owner: bool = True,
    ) -> None:
        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        schema: dict | None = None
        source = "last build JSON"

        if json_file:
            if not json_file.filename.endswith(".json"):
                return await interaction.followup.send(
                    embed=error_embed("Invalid File", "Please upload a `.json` file."),
                    ephemeral=True,
                )
            try:
                schema = self._parse_server_schema((await json_file.read()).decode("utf-8"))
                source = f"uploaded file `{json_file.filename}`"
            except (UnicodeDecodeError, ValueError) as exc:
                return await interaction.followup.send(embed=error_embed("Invalid JSON", str(exc)), ephemeral=True)
        elif json_text:
            try:
                schema = self._parse_server_schema(json_text)
                source = "pasted JSON"
            except ValueError as exc:
                return await interaction.followup.send(embed=error_embed("Invalid JSON", str(exc)), ephemeral=True)
        elif template and template.value == "example":
            schema = DETAILED_EXAMPLE_TEMPLATE
            source = "Detailed Example template"
        elif template and template.value != "last":
            schema = TEMPLATES.get(template.value)
            source = f"{template.name} template"
        else:
            schema = self._load_last_schema(interaction.guild.id)

        if not schema:
            return await interaction.followup.send(
                embed=error_embed(
                    "No JSON Available",
                    "I do not have a saved build JSON for this server yet. Use `json_text`, `json_file`, or choose a template.",
                ),
                ephemeral=True,
            )

        ok, issues, sync_text = await self._run_perm_sync_report(
            interaction.guild,
            schema,
            source,
            dm_owner=dm_owner,
        )
        embed = success_embed("Perm Sync OK OK", sync_text) if ok else error_embed("Perm Sync Issues", sync_text)
        embed.add_field(name="Source", value=source, inline=False)
        embed.add_field(name="Issues", value=str(len(issues)), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="generate_server",
        description="Generate and build a server from an AI-generated template.",
    )
    @app_commands.describe(
        theme="Describe the server theme (e.g., 'gaming community', 'study group')",
        preview="Only generate and preview; never offer execution",
        server_icon="Optional image to set as the server picture/icon",
        admin_role="Use an existing admin role instead of creating a new one",
        mod_role="Use an existing moderator role instead of creating a new one",
        enable_verification="Create a verification gate after the AI build finishes",
        perm_sync_after_build="After build, check JSON roles/channel permissions and DM the owner",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def generate_server(
        self,
        interaction: discord.Interaction,
        theme: str,
        preview: bool = False,
        server_icon: discord.Attachment | None = None,
        admin_role: discord.Role | None = None,
        mod_role: discord.Role | None = None,
        enable_verification: bool = False,
        perm_sync_after_build: bool = True,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(thinking=True)

        # Ask AI for a server schema
        raw = await ai_service.get_ai_response(
            _GENERATION_PROMPT.format(theme=theme),
            interaction.user.id,
            guild_id=interaction.guild_id,
        )

        if raw.startswith("\u26a0\ufe0f"):
            em = error_embed("AI Error", raw)
            await interaction.followup.send(embed=em)
            return

        try:
            schema = self._parse_server_schema(raw)
        except ConfigurationError as exc:
            await interaction.followup.send(embed=error_embed("AI configuration rejected", str(exc)), ephemeral=True)
            return
        selected_roles = self._selected_role_map(admin_role, mod_role)
        if preview:
            await self._send_build_preview(interaction, schema, selected_roles=selected_roles)
            return
        await self._run_custom_schema_setup(
            interaction=interaction, schema=schema, clean_existing=False, server_icon=server_icon,
            selected_roles=selected_roles, title="Last Check: AI Generated Server",
            reason_prefix="AI setup", enable_verification=enable_verification,
            perm_sync_after_build=perm_sync_after_build,
        )

    async def _send_build_preview(
        self, interaction: discord.Interaction, schema: dict, *,
        selected_roles: dict[str, discord.Role] | None = None, clean_existing: bool = False,
    ) -> None:
        plan = plan_build(interaction.guild, ServerConfig.from_dict(schema),
                          selected_roles=selected_roles, clean_existing=clean_existing,
                          safe_channel_id=interaction.channel_id)
        file = discord.File(io.BytesIO(json.dumps(plan.to_dict(), indent=2).encode()),
                            filename="server_build_plan.json")
        await interaction.followup.send(embed=info_embed("Build Preview - No Changes", plan.summary()),
                                        file=file, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="build_preview", description="Validate and plan a template or JSON file without changing anything.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(template=TEMPLATE_CHOICES)
    async def build_preview(
        self, interaction: discord.Interaction, template: app_commands.Choice[str] | None = None,
        json_file: discord.Attachment | None = None, clean_existing: bool = False,
        admin_role: discord.Role | None = None, mod_role: discord.Role | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if (template is None) == (json_file is None):
                raise ConfigurationError(["Choose exactly one template or JSON file."])
            if json_file is not None:
                if json_file.size > MAX_CONFIG_BYTES:
                    raise ConfigurationError(["JSON must be 1 MiB or smaller."])
                schema = self._parse_server_schema((await json_file.read()).decode("utf-8-sig"))
            else:
                schema = load_template(template.value)
            await self._send_build_preview(interaction, schema,
                selected_roles=self._selected_role_map(admin_role, mod_role), clean_existing=clean_existing)
        except (ConfigurationError, UnicodeDecodeError) as exc:
            text = str(exc) if isinstance(exc, ConfigurationError) else "Upload UTF-8 JSON text."
            await interaction.followup.send(embed=error_embed("Invalid configuration", text), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerBuilderCog(bot))
