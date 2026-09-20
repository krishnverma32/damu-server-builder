"""Load bundled JSON templates independently of the Discord cog."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def load_template(name: str) -> dict[str, Any]:
    """Return a fresh template; never permit caller-controlled filesystem paths."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError("Invalid template name.")
    return json.loads((TEMPLATE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def load_templates() -> dict[str, dict[str, Any]]:
    return {p.stem: load_template(p.stem) for p in sorted(TEMPLATE_DIR.glob("*.json"))
            if p.stem != "example"}
