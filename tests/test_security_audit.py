"""Security test to ensure no hardcoded secrets or credentials exist in tracked files."""

import pathlib
import re


def test_no_hardcoded_secrets():
    secret_patterns = [
        re.compile(r"DISCORD_TOKEN\s*=\s*['\"][A-Za-z0-9_\-\.]{25,}['\"]"),
        re.compile(r"mongodb(?:\+srv)?://[^\s'\"<]+:[^\s'\"<]+@"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
    ]
    ignored_patterns = {".pytest_cache", "venv", ".git", "package-lock.json", ".env"}

    for p in pathlib.Path(".").rglob("*"):
        if not p.is_file():
            continue
        if any(ign in str(p) for ign in ignored_patterns):
            continue
        content = p.read_text(encoding="utf-8", errors="ignore")
        for pat in secret_patterns:
            matches = pat.findall(content)
            assert not matches, f"Potential secret matched in {p}: {pat.pattern}"
