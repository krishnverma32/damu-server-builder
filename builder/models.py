"""Immutable configuration boundary and serializable read-only build plans."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from builder.validator import parse_json, validate_config


@dataclass(frozen=True)
class ServerConfig:
    """Store normalized JSON, so callers cannot mutate a reviewed configuration."""

    _json: str

    @classmethod
    def from_dict(cls, value: Any) -> ServerConfig:
        return cls(json.dumps(validate_config(value), sort_keys=True))

    @classmethod
    def from_json(cls, value: str) -> ServerConfig:
        return cls(json.dumps(parse_json(value), sort_keys=True))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._json)


@dataclass(frozen=True)
class PlanStep:
    action: str
    resource: str
    name: str
    path: str
    resource_id: int | None = None


@dataclass(frozen=True)
class BuildPlan:
    config: ServerConfig
    steps: tuple[PlanStep, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    overwrite_count: int

    def require_valid(self) -> None:
        from builder.exceptions import ConfigurationError
        if self.errors:
            raise ConfigurationError(list(self.errors))

    def summary(self) -> str:
        lines = ["BUILD PLAN (read-only)"]
        for action in ("create", "reuse", "update", "delete"):
            counts = {kind: sum(s.action == action and s.resource == kind for s in self.steps)
                      for kind in ("role", "category", "channel", "thread", "server")}
            if any(counts.values()):
                lines.append(f"{action.title()}: " + ", ".join(f"{v} {k}(s)" for k, v in counts.items() if v))
        lines.append(f"Validated overwrites: {self.overwrite_count}")
        lines.append(f"Warnings: {len(self.warnings)} | Blocking issues: {len(self.errors)}")
        lines.extend(f"BLOCKED: {issue}" for issue in self.errors[:6])
        lines.extend(f"Warning: {issue}" for issue in self.warnings[:6])
        return "\n".join(lines)[:3500]

    def to_dict(self) -> dict[str, Any]:
        return {"config": self.config.to_dict(), "steps": [asdict(s) for s in self.steps],
                "warnings": list(self.warnings), "errors": list(self.errors),
                "overwrite_count": self.overwrite_count}
