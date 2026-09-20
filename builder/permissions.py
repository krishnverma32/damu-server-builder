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
            log.warning("Unknown permission name: %s", name)
    return discord.Permissions(value)


