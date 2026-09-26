"""Keep-alive and health server for Render deployment."""

from __future__ import annotations

import json
import logging
import os
from threading import Thread
from typing import Optional

from flask import Flask, Response, jsonify

from core.diagnostics import get_diagnostic_status
from core.startup.manager import StartupManager

log = logging.getLogger("core.health_server")

health_app = Flask("damu_health_server")


@health_app.route("/")
def root_check():
    """Root endpoint for legacy pingers."""
    return "Bot is alive!", 200


@health_app.route("/health")
def health_check():
    """Process health endpoint.

    CRITICAL: Always returns HTTP 200 while the Python process is alive.
    Render health checks should point here to prevent restarts during Discord API blocks.
    """
    return jsonify({"status": "ok", "process": "alive"}), 200


@health_app.route("/ready")
def readiness_check():
    """Discord readiness endpoint.

    Returns:
        HTTP 200 if Discord connection is active and API is available.
        HTTP 503 if Discord is rate limited, blocked, connecting, or degraded.
    """
    diag = get_diagnostic_status()
    payload = diag.to_dict()

    if diag.discord_ready:
        payload["status"] = "ready"
        payload["discord"] = "ready"
        return jsonify(payload), 200
    else:
        payload["status"] = "not_ready"
        payload["discord"] = "degraded"
        return jsonify(payload), 503



def start_health_server(port: Optional[int] = None) -> Thread:
    """Start the health server in a background daemon thread."""
    server_port = port or int(os.environ.get("PORT", 8080))

    def _run():
        log.info("Starting health server on port %d...", server_port)
        # Disable Flask development banner and request logging noise
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.WARNING)
        health_app.run(host="0.0.0.0", port=server_port, use_reloader=False)

    thread = Thread(target=_run, daemon=True, name="DamuHealthServer")
    thread.start()
    return thread
