"""Logging setup — rotating file handler + coloured console output + sanitizing filter."""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

# ── ANSI colour codes ─────────────────────────────────────────────────────────
_RESET = "\033[0m"
_COLOURS: dict[int, str] = {
    logging.DEBUG: "\033[37m",  # white
    logging.INFO: "\033[36m",  # cyan
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}

_REDACTION_RULES = [
    (re.compile(r"(mongodb(?:\+srv)?://[^:]+:)[^@]+(@)", re.IGNORECASE), r"\1***\2"),
    (re.compile(r"(Authorization:\s*(?:Bot|Bearer)\s+)[^\s]+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(\bBearer\s+)[A-Za-z0-9._-]{20,}", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(\bBot\s+)[A-Za-z0-9._-]{20,}", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(token\s*=\s*['\"])[^'\"]+(['\"])", re.IGNORECASE), r"\1***REDACTED***\2"),
    (re.compile(r"<!DOCTYPE html>.*?</html>", re.DOTALL | re.IGNORECASE), "[Cloudflare HTML Response - Error 1015]"),
    (re.compile(r"<html.*?>.*?</html>", re.DOTALL | re.IGNORECASE), "[HTML Response]"),
]


class SanitizingFilter(logging.Filter):
    """Filter that intercepts and scrubs sensitive tokens and giant HTML payloads."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            # Strip Cloudflare HTML dumps
            if "<!DOCTYPE html" in msg or "<html" in msg:
                if "1015" in msg or "Cloudflare" in msg or "rate limited" in msg:
                    msg = "[Cloudflare HTML Block Response - Error 1015]"
                else:
                    msg = "[HTML Response Truncated]"

            # Redact secrets
            for pattern, repl in _REDACTION_RULES:
                msg = pattern.sub(repl, msg)
            record.msg = msg

        return True


class ColouredFormatter(logging.Formatter):
    """Formatter that prepends an ANSI colour code based on log level."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _COLOURS.get(record.levelno, _RESET)
        record.msg = f"{colour}{record.msg}{_RESET}"
        return super().format(record)


def setup_logging() -> None:
    """Configure root logger with console + rotating file handlers."""
    os.makedirs("logs", exist_ok=True)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Attach sanitizing filter
    sanitizer = SanitizingFilter()
    root.addFilter(sanitizer)

    # ── Console handler (coloured) ────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(ColouredFormatter(fmt, datefmt=datefmt))
    console.addFilter(sanitizer)
    root.addHandler(console)

    # ── All-levels rotating file handler ──────────────────────────────────────
    all_file = RotatingFileHandler(
        "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    all_file.setLevel(logging.DEBUG)
    all_file.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    all_file.addFilter(sanitizer)
    root.addHandler(all_file)

    # ── Error-only rotating file handler ──────────────────────────────────────
    err_file = RotatingFileHandler(
        "logs/error.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    err_file.setLevel(logging.ERROR)
    err_file.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    err_file.addFilter(sanitizer)
    root.addHandler(err_file)

    # Suppress noisy discord.py HTTP debug logs
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
