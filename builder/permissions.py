"""Shared Discord permission resolution."""
import logging
import discord

log = logging.getLogger(__name__)

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
            raise ValueError(f"Unknown permission name: {name}")
    return discord.Permissions(value)


resolve_permissions = _resolve_permissions

# ── Category grouping for the permission editor UI ─────────────────────────────
PERMISSION_CATEGORIES: dict[str, list[str]] = {
    "GENERAL": [
        "view_channel",
        "manage_channels",
        "manage_roles",
        "manage_webhooks",
        "view_audit_log",
    ],
    "MESSAGES": [
        "send_messages",
        "send_messages_in_threads",
        "embed_links",
        "attach_files",
        "add_reactions",
        "mention_everyone",
        "read_message_history",
        "use_external_emojis",
    ],
    "MODERATION": [
        "manage_messages",
        "manage_threads",
        "kick_members",
        "ban_members",
        "mute_members",
        "deafen_members",
        "move_members",
    ],
    "VOICE": [
        "connect",
        "speak",
        "mute_members",
        "deafen_members",
        "move_members",
    ],
}

# ── Reusable Channel Permission Presets ────────────────────────────────────────
PERMISSION_PRESETS: dict[str, dict[str, dict[str, list[str]]]] = {
    "Public Chat": {
        "@everyone": {
            "allow": ["view_channel", "send_messages", "read_message_history", "add_reactions"],
            "deny": ["mention_everyone"],
        }
    },
    "Read Only": {
        "@everyone": {
            "allow": ["view_channel", "read_message_history", "add_reactions"],
            "deny": ["send_messages", "send_messages_in_threads", "create_public_threads"],
        }
    },
    "Announcement": {
        "@everyone": {
            "allow": ["view_channel", "read_message_history"],
            "deny": ["send_messages", "send_messages_in_threads", "add_reactions"],
        },
        "Moderator": {
            "allow": ["send_messages", "mention_everyone"],
            "deny": [],
        },
        "Admin": {
            "allow": ["send_messages", "mention_everyone"],
            "deny": [],
        },
    },
    "Staff Only": {
        "@everyone": {
            "allow": [],
            "deny": ["view_channel"],
        },
        "Staff": {
            "allow": ["view_channel", "send_messages", "manage_messages", "read_message_history"],
            "deny": [],
        },
        "Moderator": {
            "allow": ["view_channel", "send_messages", "manage_messages", "read_message_history"],
            "deny": [],
        },
        "Admin": {
            "allow": ["view_channel", "send_messages", "manage_channels", "manage_messages", "read_message_history"],
            "deny": [],
        },
    },
    "Admin Only": {
        "@everyone": {
            "allow": [],
            "deny": ["view_channel"],
        },
        "Admin": {
            "allow": ["view_channel", "send_messages", "manage_channels", "manage_messages", "read_message_history"],
            "deny": [],
        },
    },
    "Moderator Only": {
        "@everyone": {
            "allow": [],
            "deny": ["view_channel"],
        },
        "Moderator": {
            "allow": ["view_channel", "send_messages", "manage_messages", "read_message_history"],
            "deny": [],
        },
    },
    "VIP Only": {
        "@everyone": {
            "allow": [],
            "deny": ["view_channel"],
        },
        "VIP": {
            "allow": ["view_channel", "send_messages", "embed_links", "attach_files", "read_message_history"],
            "deny": [],
        },
    },
    "Media": {
        "@everyone": {
            "allow": ["view_channel", "send_messages", "embed_links", "attach_files", "add_reactions", "read_message_history"],
            "deny": [],
        }
    },
    "Support": {
        "@everyone": {
            "allow": ["view_channel", "send_messages", "read_message_history"],
            "deny": [],
        },
        "Support": {
            "allow": ["view_channel", "send_messages", "manage_messages", "read_message_history"],
            "deny": [],
        },
    },
    "Private": {
        "@everyone": {
            "allow": [],
            "deny": ["view_channel"],
        }
    },
    "Voice Members": {
        "@everyone": {
            "allow": ["view_channel", "connect", "speak"],
            "deny": ["mute_members", "deafen_members", "move_members"],
        }
    },
    "Creator": {
        "@everyone": {
            "allow": ["view_channel", "read_message_history"],
            "deny": ["send_messages"],
        },
        "Creator": {
            "allow": ["view_channel", "send_messages", "embed_links", "attach_files", "mention_everyone"],
            "deny": [],
        },
    },
}

# ── Reusable Role Presets ──────────────────────────────────────────────────────
ROLE_PRESETS: dict[str, dict[str, Any]] = {
    "Owner": {
        "color": "gold",
        "hoist": True,
        "mentionable": True,
        "permissions": ["administrator"],
    },
    "Admin": {
        "color": "red",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "administrator",
            "manage_guild",
            "manage_roles",
            "manage_channels",
            "kick_members",
            "ban_members",
            "manage_messages",
            "view_audit_log",
        ],
    },
    "Moderator": {
        "color": "blue",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "manage_messages",
            "kick_members",
            "ban_members",
            "mute_members",
            "move_members",
            "manage_threads",
            "view_channel",
            "read_message_history",
        ],
    },
    "Trial Moderator": {
        "color": "teal",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "manage_messages",
            "mute_members",
            "view_channel",
            "read_message_history",
        ],
    },
    "Helper": {
        "color": "emerald",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "manage_messages",
            "view_channel",
            "read_message_history",
        ],
    },
    "Support": {
        "color": "green",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "manage_threads",
            "view_channel",
            "send_messages",
            "read_message_history",
        ],
    },
    "VIP": {
        "color": "purple",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "view_channel",
            "send_messages",
            "embed_links",
            "attach_files",
            "add_reactions",
            "use_external_emojis",
            "connect",
            "speak",
        ],
    },
    "Creator": {
        "color": "magenta",
        "hoist": True,
        "mentionable": True,
        "permissions": [
            "view_channel",
            "send_messages",
            "embed_links",
            "attach_files",
            "add_reactions",
            "mention_everyone",
        ],
    },
    "Verified Member": {
        "color": "blurple",
        "hoist": False,
        "mentionable": False,
        "permissions": [
            "view_channel",
            "send_messages",
            "add_reactions",
            "use_external_emojis",
            "connect",
            "speak",
        ],
    },
    "Muted": {
        "color": "grey",
        "hoist": False,
        "mentionable": False,
        "permissions": [],
    },
    "Bot": {
        "color": "orange",
        "hoist": True,
        "mentionable": False,
        "permissions": [
            "view_channel",
            "send_messages",
            "embed_links",
            "attach_files",
            "add_reactions",
            "read_message_history",
        ],
    },
}


def tri_state_to_overwrite(states: dict[str, bool | None]) -> discord.PermissionOverwrite:
    """Construct a discord.PermissionOverwrite from a dict of {perm_name: True|False|None}."""
    kwargs: dict[str, bool | None] = {}
    for name, val in states.items():
        attr = name.lower()
        if hasattr(discord.PermissionOverwrite, attr):
            kwargs[attr] = val
    return discord.PermissionOverwrite(**kwargs)


def overwrite_to_tri_state(overwrite: discord.PermissionOverwrite) -> dict[str, bool | None]:
    """Convert a discord.PermissionOverwrite into a dict of {perm_name: True|False|None}."""
    result: dict[str, bool | None] = {}
    for perm_name in _PERM_MAP:
        if hasattr(overwrite, perm_name):
            val = getattr(overwrite, perm_name)
            result[perm_name] = val
    return result



