"""AI Natural Language Server Editor — safe structured output translation."""
from __future__ import annotations

import json
import logging
from typing import Any

import discord

from builder.diff import ServerDiffResult, calculate_server_diff
from builder.models import ServerConfig
from builder.snapshot import take_guild_snapshot
from builder.validator import validate_config
from services import ai_service

log = logging.getLogger(__name__)

_AI_EDIT_SYSTEM_PROMPT = (
    "You are Damu Server Builder's configuration assistant.\n"
    "An administrator has provided an instruction to modify their Discord server.\n"
    "Your job is to produce a valid JSON object matching the Damu ServerConfig schema representing the desired server layout.\n"
    "CRITICAL RULES:\n"
    "1. Return ONLY the JSON object. No explanations, no markdown formatting outside the JSON.\n"
    "2. The JSON MUST adhere to the Damu Server schema:\n"
    '   {\n'
    '     "server_name": "string",\n'
    '     "roles": [{"name": "string", "color": "string", "hoist": bool, "mentionable": bool, "permissions": ["string"]}],\n'
    '     "categories": [{\n'
    '       "name": "string",\n'
    '       "permission_overwrites": [{"role": "string", "allow": ["string"], "deny": ["string"]}],\n'
    '       "channels": [{\n'
    '         "type": "text|voice|forum|stage|announcement",\n'
    '         "name": "string",\n'
    '         "topic": "string",\n'
    '         "slowmode": 0,\n'
    '         "nsfw": false,\n'
    '         "permission_overwrites": [{"role": "string", "allow": ["string"], "deny": ["string"]}]\n'
    '       }]\n'
    '     }]\n'
    '   }\n'
    "3. Incorporate the user's requested changes into the provided current layout.\n"
    "4. For channel permission modifications (e.g. 'make #announcements read-only'):\n"
    "   Set deny: ['send_messages'] for @everyone, allow: ['view_channel', 'read_message_history'].\n"
)


async def plan_natural_language_edit(
    guild: discord.Guild,
    user_id: int,
    instruction: str,
) -> tuple[ServerConfig, ServerDiffResult]:
    """Process natural language request into a validated ServerConfig and deterministic Diff.

    Never mutates Discord state.
    """
    current_layout = take_guild_snapshot(guild)
    prompt = (
        f"{_AI_EDIT_SYSTEM_PROMPT}\n\n"
        f"CURRENT SERVER LAYOUT:\n{json.dumps(current_layout, indent=2)}\n\n"
        f"ADMINISTRATOR INSTRUCTION: {instruction}\n\n"
        "OUTPUT THE COMPLETE UPDATED JSON SCHEMA:"
    )

    response_text = await ai_service.get_ai_response(
        prompt,
        user_id=user_id,
        guild_id=guild.id,
    )

    # Clean potential markdown fences
    cleaned = response_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    config = ServerConfig.from_dict(data)
    diff = calculate_server_diff(guild, config)
    return config, diff
