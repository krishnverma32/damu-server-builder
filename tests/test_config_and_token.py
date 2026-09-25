"""Tests for configuration parsing, token validation, and Flask endpoints."""

import os
import tempfile
import pytest
from dotenv import load_dotenv

import config
from main import _keep_alive_app


def test_normalize_token_empty():
    assert config.normalize_token("") == ""
    assert config.normalize_token(None) == ""
    assert config.normalize_token("   \n\t  ") == ""


def test_normalize_token_whitespace():
    assert config.normalize_token("   secret_with_spaces   \n") == "secret_with_spaces"


def test_normalize_token_double_quotes():
    assert config.normalize_token('  "my_double_quoted_secret"  ') == "my_double_quoted_secret"


def test_normalize_token_single_quotes():
    assert config.normalize_token("  'my_single_quoted_secret'  ") == "my_single_quoted_secret"


def test_normalize_token_nested_quotes():
    assert config.normalize_token('  "\'nested_quoted_secret\'"  ') == "nested_quoted_secret"


def test_render_env_priority_over_dotenv():
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
        f.write("DISCORD_TOKEN=file_token_value\n")
        env_path = f.name

    try:
        os.environ["DISCORD_TOKEN"] = "render_host_token"
        load_dotenv(dotenv_path=env_path, override=False)
        assert os.environ["DISCORD_TOKEN"] == "render_host_token"
    finally:
        os.remove(env_path)


def test_validate_discord_token_missing():
    with pytest.raises(RuntimeError, match="DISCORD_TOKEN is missing or empty"):
        config.validate_discord_token("")
    with pytest.raises(RuntimeError, match="DISCORD_TOKEN is missing or empty"):
        config.validate_discord_token("   ")


def test_validate_discord_token_placeholder():
    with pytest.raises(RuntimeError, match="placeholder value"):
        config.validate_discord_token("your_bot_token")
    with pytest.raises(RuntimeError, match="placeholder value"):
        config.validate_discord_token("your_discord_bot_token_here")
    with pytest.raises(RuntimeError, match="placeholder value"):
        config.validate_discord_token("changeme")


def test_validate_discord_token_valid():
    # Valid synthetic token string should not raise any exceptions
    config.validate_discord_token("MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.G_abcd.1234567890abcdef")


def test_flask_health_endpoints():
    client = _keep_alive_app.test_client()
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert b"Bot is alive!" in resp_root.data

    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert b"Bot is alive!" in resp_health.data

    resp_terms = client.get("/terms.html")
    assert resp_terms.status_code == 200
    assert b"DAMU Server Builder" in resp_terms.data
    assert b"Last Updated" in resp_terms.data

    resp_privacy = client.get("/privacy.html")
    assert resp_privacy.status_code == 200
    assert b"DAMU Server Builder" in resp_privacy.data
    assert b"Last Updated" in resp_privacy.data


def test_main_startup_diagnostics_and_401(monkeypatch):
    import subprocess
    import sys

    env = os.environ.copy()
    env["DISCORD_TOKEN"] = '  "test_synthetic_token_123456789"  '

    res = subprocess.run(
        [sys.executable, "main.py"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    combined = res.stderr + "\n" + res.stdout

    assert res.returncode == 1
    assert "DISCORD_TOKEN environment variable detected: YES" in combined
    assert "token length detected: YES" in combined
    assert (
        "Discord authentication failed (401). The configured Discord bot token was rejected by Discord."
        in combined
    )
    # Ensure token was not printed in output
    assert "test_synthetic_token_123456789" not in combined
