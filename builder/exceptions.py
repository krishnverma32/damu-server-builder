"""User-facing errors that contain no tokens or Discord tracebacks."""
from __future__ import annotations


class ConfigurationError(ValueError):
    """A configuration was rejected before any resource mutation."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = tuple(issues)
        summary = "\n".join(issues[:12])
        if len(issues) > 12:
            summary += f"\n...and {len(issues) - 12} more issues."
        super().__init__(summary[:1800])
