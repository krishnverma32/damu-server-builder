"""DAMU Core Engine — Central architecture for Discord server management."""

from core.errors import (
    DamuError,
    ErrorCategory,
    classify_error,
    format_user_error,
)
from core.interaction import (
    InteractionSafety,
    interaction_alive,
    is_acknowledged,
    safe_defer,
    safe_edit,
    safe_followup,
    safe_modal,
    safe_send,
)
from core.models import (
    Action,
    ActionStatus,
    ActionType,
    BuildPlan,
    EngineResult,
    RiskLevel,
)

__all__ = [
    "DamuError",
    "ErrorCategory",
    "classify_error",
    "format_user_error",
    "InteractionSafety",
    "interaction_alive",
    "is_acknowledged",
    "safe_defer",
    "safe_send",
    "safe_followup",
    "safe_edit",
    "safe_modal",
    "Action",
    "ActionStatus",
    "ActionType",
    "BuildPlan",
    "EngineResult",
    "RiskLevel",
]
