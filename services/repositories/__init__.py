"""Repository exports for clean persistence access across the platform."""

from services.repositories.base import BaseRepository
from services.repositories.ticket_repository import TicketRepository
from services.repositories.automod_repository import AutoModRepository
from services.repositories.guild_repository import GuildRepository
from services.repositories.build_repository import BuildRepository
from services.repositories.snapshot_repository import SnapshotRepository
from services.repositories.moderation_repository import ModerationRepository
from services.repositories.analytics_repository import AnalyticsRepository

__all__ = [
    "BaseRepository",
    "TicketRepository",
    "AutoModRepository",
    "GuildRepository",
    "BuildRepository",
    "SnapshotRepository",
    "ModerationRepository",
    "AnalyticsRepository",
]
