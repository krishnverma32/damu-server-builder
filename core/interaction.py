"""Interaction Safety Layer — Guarantees safe interaction acknowledgements and lifecycle handling.

Eliminates Discord 10062 'Unknown interaction' errors by strictly enforcing acknowledgement
order and handling timeouts and response states gracefully.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Sequence

import discord

log = logging.getLogger("core.interaction")

# Discord interaction response deadline is 3 seconds; token lifecycle is 15 minutes.
MAX_INTERACTION_AGE_SECONDS = 900.0  # 15 minutes


def is_acknowledged(interaction: discord.Interaction) -> bool:
    """Return True if the interaction response has already been sent or deferred."""
    try:
        return interaction.response.is_done()
    except Exception:
        return False


def interaction_alive(interaction: discord.Interaction) -> bool:
    """Check if the interaction is within its valid lifetime (15 minutes)."""
    try:
        if not interaction.created_at:
            return True
        now = datetime.now(timezone.utc)
        elapsed = (now - interaction.created_at).total_seconds()
        return elapsed < MAX_INTERACTION_AGE_SECONDS
    except Exception:
        return True


async def safe_defer(
    interaction: discord.Interaction,
    *,
    ephemeral: bool = True,
    thinking: bool = False,
) -> bool:
    """Immediately acknowledge and defer an interaction if not already acknowledged.

    Returns True if the interaction is acknowledged and usable, False if expired or failed.
    """
    if is_acknowledged(interaction):
        return True

    if not interaction_alive(interaction):
        log.warning("Interaction %s is expired (age > 15m). Cannot defer.", getattr(interaction, "id", "unknown"))
        return False

    try:
        await interaction.response.defer(ephemeral=ephemeral, thinking=thinking)
        return True
    except discord.NotFound as exc:
        # Error code 10062: Unknown interaction
        if getattr(exc, "code", None) == 10062:
            log.warning("Interaction %s expired before deferral (10062 Unknown interaction).", getattr(interaction, "id", "unknown"))
        else:
            log.warning("NotFound during safe_defer: %s", exc)
        return False
    except discord.InteractionResponded:
        return True
    except discord.HTTPException as exc:
        log.warning("HTTPException during safe_defer: %s", exc)
        return False
    except Exception as exc:
        log.error("Unexpected error in safe_defer: %s", exc, exc_info=True)
        return False


async def safe_send(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    embeds: Sequence[discord.Embed] | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
    file: discord.File | None = None,
    files: Sequence[discord.File] | None = None,
    delete_after: float | None = None,
) -> discord.Message | discord.WebhookMessage | None:
    """Safely deliver a message to the user regardless of interaction state.

    If not acknowledged: uses interaction.response.send_message.
    If already acknowledged: uses interaction.followup.send.
    Handles 10062, already-responded, and expired interactions safely.
    """
    kwargs: dict[str, Any] = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    if view is not None:
        kwargs["view"] = view
    if ephemeral:
        kwargs["ephemeral"] = ephemeral
    if file is not None:
        kwargs["file"] = file
    if files is not None:
        kwargs["files"] = files
    if delete_after is not None:
        kwargs["delete_after"] = delete_after

    try:
        if is_acknowledged(interaction):
            return await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
            return None
    except discord.InteractionResponded:
        # State changed concurrently, retry via followup
        try:
            return await interaction.followup.send(**kwargs)
        except Exception as exc:
            log.warning("Failed followup after InteractionResponded: %s", exc)
            return None
    except discord.NotFound as exc:
        if getattr(exc, "code", None) == 10062:
            log.warning("safe_send failed: 10062 Unknown interaction for %s", getattr(interaction, "id", "unknown"))
            # Fallback to channel.send if interaction is completely dead and channel is accessible
            if interaction.channel and hasattr(interaction.channel, "send") and not ephemeral:
                try:
                    kwargs.pop("ephemeral", None)
                    return await interaction.channel.send(**kwargs)
                except Exception:
                    pass
        else:
            log.warning("NotFound during safe_send: %s", exc)
        return None
    except discord.HTTPException as exc:
        log.warning("HTTPException in safe_send: %s", exc)
        return None
    except Exception as exc:
        log.error("Unexpected error in safe_send: %s", exc, exc_info=True)
        return None


async def safe_followup(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    embeds: Sequence[discord.Embed] | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
    file: discord.File | None = None,
    files: Sequence[discord.File] | None = None,
) -> discord.WebhookMessage | None:
    """Send a followup response, ensuring acknowledgement first if necessary."""
    kwargs: dict[str, Any] = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    if view is not None:
        kwargs["view"] = view
    if ephemeral:
        kwargs["ephemeral"] = ephemeral
    if file is not None:
        kwargs["file"] = file
    if files is not None:
        kwargs["files"] = files

    if not is_acknowledged(interaction):
        deferred = await safe_defer(interaction, ephemeral=ephemeral)
        if not deferred:
            # Try direct send
            await safe_send(interaction, **kwargs)
            return None

    try:
        return await interaction.followup.send(**kwargs)
    except discord.NotFound as exc:
        if getattr(exc, "code", None) == 10062:
            log.warning("safe_followup failed: 10062 Unknown interaction")
        return None
    except discord.HTTPException as exc:
        log.warning("HTTPException in safe_followup: %s", exc)
        return None
    except Exception as exc:
        log.error("Unexpected error in safe_followup: %s", exc, exc_info=True)
        return None


async def safe_edit(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    embeds: Sequence[discord.Embed] | None = None,
    view: discord.ui.View | None = None,
    file: discord.File | None = None,
    files: Sequence[discord.File] | None = None,
) -> None:
    """Safely edit the current message or original response."""
    kwargs: dict[str, Any] = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    if view is not None:
        kwargs["view"] = view
    if file is not None:
        kwargs["file"] = file
    if files is not None:
        kwargs["files"] = files

    try:
        if not is_acknowledged(interaction):
            await interaction.response.edit_message(**kwargs)
        else:
            await interaction.edit_original_response(**kwargs)
    except discord.NotFound:
        log.warning("safe_edit failed: message or interaction not found.")
    except discord.InteractionResponded:
        try:
            await interaction.edit_original_response(**kwargs)
        except Exception as exc:
            log.warning("safe_edit edit_original_response failed: %s", exc)
    except discord.HTTPException as exc:
        log.warning("safe_edit HTTPException: %s", exc)
    except Exception as exc:
        log.error("Unexpected error in safe_edit: %s", exc, exc_info=True)


async def safe_modal(
    interaction: discord.Interaction,
    modal: discord.ui.Modal,
) -> bool:
    """Safely send a modal.

    Modals CANNOT be sent if the interaction has already been acknowledged or deferred.
    Returns True if sent, False otherwise.
    """
    if is_acknowledged(interaction):
        log.warning("Cannot send modal on an already-acknowledged interaction.")
        await safe_followup(
            interaction,
            content="⚠️ This action requested a form input, but the interaction was already acknowledged. Please click the button again.",
            ephemeral=True,
        )
        return False

    try:
        await interaction.response.send_modal(modal)
        return True
    except discord.NotFound:
        log.warning("safe_modal failed: 10062 Unknown interaction.")
        return False
    except discord.InteractionResponded:
        log.warning("safe_modal failed: interaction was already responded to.")
        return False
    except discord.HTTPException as exc:
        log.warning("safe_modal HTTPException: %s", exc)
        return False
    except Exception as exc:
        log.error("Unexpected error in safe_modal: %s", exc, exc_info=True)
        return False


class InteractionSafety:
    """Unified wrapper around interaction safety helpers."""

    safe_defer = staticmethod(safe_defer)
    safe_send = staticmethod(safe_send)
    safe_followup = staticmethod(safe_followup)
    safe_edit = staticmethod(safe_edit)
    safe_modal = staticmethod(safe_modal)
    is_acknowledged = staticmethod(is_acknowledged)
    interaction_alive = staticmethod(interaction_alive)
