"""Bot configuration — reads from environment variables and exposes typed constants."""

from __future__ import annotations

import os
from dotenv import load_dotenv

# Ensure hosting provider (e.g. Render) environment variables take precedence
load_dotenv(override=False)


def normalize_token(raw_token: str | None) -> str:
    """Safely normalize a token string by removing surrounding whitespace and matching quotes.

    Never prints or logs secret contents or character values.
    """
    if not raw_token:
        return ""
    val = raw_token.strip()
    while len(val) >= 2 and (
        (val.startswith('"') and val.endswith('"'))
        or (val.startswith("'") and val.endswith("'"))
    ):
        val = val[1:-1].strip()
    return val


def _get_clean_secret(var_name: str) -> str:
    """Safely fetch and normalize secret strings directly from environment variables."""
    raw = os.getenv(var_name)
    if not raw:
        return ""
    return normalize_token(raw)


def _get_int_env(var_name: str, default: int = 0) -> int:
    """Safely parse integer environment variables."""
    raw = os.getenv(var_name)
    if not raw:
        return default
    cleaned = raw.strip().strip('"').strip("'")
    try:
        return int(cleaned)
    except ValueError:
        return default


def _get_int_list_env(var_name: str) -> list[int]:
    """Safely parse comma-separated integer list environment variables."""
    raw = os.getenv(var_name, "")
    cleaned = raw.strip().strip('"').strip("'")
    result: list[int] = []
    for item in cleaned.split(","):
        item = item.strip()
        if item:
            try:
                result.append(int(item))
            except ValueError:
                continue
    return result


def validate_discord_token(token: str) -> None:
    """Validate token presence and check for common placeholder mistakes.

    Never prints or exposes the actual token value.
    """
    if not token or not token.strip():
        raise RuntimeError(
            "DISCORD_TOKEN is missing or empty. "
            "Please configure the DISCORD_TOKEN environment variable in your hosting provider settings "
            "(e.g., Render Dashboard -> Environment -> Environment Variables)."
        )

    known_placeholders = {
        "your_bot_token",
        "your_token_here",
        "your_discord_token_here",
        "your_discord_bot_token_here",
        "bot_token",
        "changeme",
        "placeholder",
    }
    if token.strip().lower() in known_placeholders:
        raise RuntimeError(
            "DISCORD_TOKEN is currently set to an example placeholder value. "
            "Please update it with your actual Discord Bot Token in the hosting environment variables."
        )


# ── Core Secrets & Integrations ───────────────────────────────────────────────
# Reads the exact DISCORD_TOKEN environment variable configured in hosting (Render)
DISCORD_TOKEN: str = normalize_token(os.getenv("DISCORD_TOKEN"))
OPENROUTER_API_KEY: str = _get_clean_secret("OPENROUTER_API_KEY")
GIPHY_API_KEY: str = _get_clean_secret("GIPHY_API_KEY")
MONGO_URI: str = _get_clean_secret("MONGO_URI")
YOUTUBE_OAUTH_TOKEN_JSON: str = _get_clean_secret("YOUTUBE_OAUTH_TOKEN_JSON")

# ── Channel / Role IDs ────────────────────────────────────────────────────────
MOD_LOG_CHANNEL_ID: int = _get_int_env("MOD_LOG_CHANNEL_ID", 0)
TICKET_LOG_CHANNEL_ID: int = _get_int_env("TICKET_LOG_CHANNEL_ID", 0)
SUPPORT_ROLE_ID: int = _get_int_env("SUPPORT_ROLE_ID", 0)

# ── Developer IDs ─────────────────────────────────────────────────────────────
DEV_IDS: list[int] = _get_int_list_env("DEV_IDS")
SERVER_BUILD_OWNER_ID: int = _get_int_env("SERVER_BUILD_OWNER_ID", 486555340670894080)
BOT_OWNER_ID: int = _get_int_env("BOT_OWNER_ID", SERVER_BUILD_OWNER_ID)
SERVER_BUILD_BYPASS_IDS: list[int] = _get_int_list_env("SERVER_BUILD_BYPASS_IDS")

# ── AI Settings ───────────────────────────────────────────────────────────────
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL: str = "nvidia/nemotron-nano-9b-v2:free"
AI_FALLBACK_MODELS: list[str] = [
    "nvidia/nemotron-nano-9b-v2:free",     # NVIDIA 9B — fast & reliable
    "arcee-ai/trinity-large-preview:free", # Arcee 400B MoE — smart
    "stepfun/step-3.5-flash:free",         # StepFun 196B MoE — reasoning
    "google/gemma-3-27b-it:free",          # Google Gemma — backup
    "arcee-ai/trinity-mini:free",          # Arcee Mini — last resort
]
AI_MAX_RETRIES: int = 2
AI_MAX_HISTORY: int = 10
AI_RATE_LIMIT: int = 5          # requests per minute per user
AI_RATE_WINDOW: float = 60.0    # seconds

# ── Leveling ──────────────────────────────────────────────────────────────────
XP_PER_MESSAGE_MIN: int = 15
XP_PER_MESSAGE_MAX: int = 25
XP_COOLDOWN: int = 60           # seconds between XP gains
LEVEL_ROLES: dict[int, int] = {}

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR: str = "data"
MEMORY_FILE: str = f"{DATA_DIR}/memory/user_memory.json"
XP_FILE: str = f"{DATA_DIR}/levels/xp_data.json"
TICKET_LOG_FILE: str = f"{DATA_DIR}/tickets/ticket_log.json"
WARNINGS_FILE: str = f"{DATA_DIR}/warnings.json"
ANALYTICS_FILE: str = f"{DATA_DIR}/analytics.json"
DASHBOARD_CONFIG_FILE: str = f"{DATA_DIR}/dashboard_config.json"
VERIFICATION_CONFIG_FILE: str = f"{DATA_DIR}/verification_config.json"
AUTOMOD_FILE: str = f"{DATA_DIR}/automod/offenses.json"

# ── Bot Meta ──────────────────────────────────────────────────────────────────
BOT_NAME: str = "DAMU Server Builder"
BOT_VERSION: str = "2.0.0"
BOT_COLOR: int = 0x5865F2       # blurple
