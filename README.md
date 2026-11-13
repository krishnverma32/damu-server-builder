# DAMU Server Builder — Core Engine V3

A modular, UI-first Discord server management and automation engine built with **Python 3.10+**, **discord.py 2.x**, **Flask**, and **MongoDB Atlas**.

> [!IMPORTANT]
> **DAMU is a Discord bot.** The primary user experience lives directly inside Discord via interactive buttons, select menus, modals, embeds, preview confirmation dialogs, and real-time progress updates. AI is used solely for natural-language understanding and plan synthesis — **AI never directly executes Discord API operations.**

---

## Architecture Overview

```text
USER (Discord UI)
  │
  ▼
REQUEST / INTENT
  │
  ▼
PLANNER (5-Tier Fallback Chain)
  │
  ▼
VALIDATOR (JSON + Semantic + Schema)
  │
  ▼
PERMISSION ENGINE (Hierarchy + Administrator Guard)
  │
  ▼
SAFETY ENGINE (Risk Assessment + User Confirmation Preview)
  │
  ▼
EXECUTION ENGINE (Rate-Limit Handling + Exponential Backoff)
  │
  ▼
VERIFICATION ENGINE (Post-Execution Validation)
  │
  ▼
RESULT UI (Visual Report + Build ID)
  │
  ▼
MEMORY / AUDIT (Structured Logs + Mod-Log Dispatch)
```

---

## Key Subsystems & Engines

### 1. Interaction Safety Layer (`core/interaction.py`)
- **Eliminates Discord 10062 Unknown Interaction**: Resolves expired interaction tokens by enforcing immediate acknowledgements (`safe_defer`) before any database, permission, or Discord API calls.
- Provides unified helpers: `safe_defer`, `safe_send`, `safe_followup`, `safe_edit`, `safe_modal`, `is_acknowledged`, and `interaction_alive`.
- Auto-recovers from `discord.InteractionResponded` and stale interactions.

### 2. Central Execution Engine (`core/engine.py`)
- Standardized execution lifecycle: `plan()` &rarr; `validate()` &rarr; `execute()` &rarr; `verify()` &rarr; `recover()`.
- Every operation produces a strongly-typed `EngineResult` containing the operation name, resource ID, list of executed actions, warnings, and recovery state.
- Transaction tracking with unique IDs (`DAMU-YYYYMMDD-XXXXX`).

### 3. Resource Engines (`engines/guild/`)
- **Channel Engine (`channel_engine.py`)**: Validated creation, editing, deletion, moving, cloning, and permission syncing across text, voice, forum, stage, and category channels.
- **Category Engine (`category_engine.py`)**: Category lifecycle management, permission presets, and orphan channel detection.
- **Role Engine (`role_engine.py`)**: Role creation, editing, hoist/color/mentionable changes, and strict hierarchy enforcement.
- **Permission Engine (`permission_engine.py`)**:
  - Presets: `PUBLIC`, `MEMBERS`, `VERIFIED`, `STAFF`, `MODERATOR`, `ADMIN`, `OWNER`, `BOT_ONLY`, `PRIVATE`, `TICKET`, `ANNOUNCEMENT`, `MEDIA`, `SUPPORT`, `CUSTOM`.
  - **Administrator Guard**: Identifies high-risk permission assignments, strips accidental admin grants, and requires explicit user confirmation.
- **Role Resolver (`role_resolver.py`)**: Maps semantic role names (`"admin"`, `"mod"`, `"staff"`) to actual guild roles. If ambiguous matches exist, prompts the user via an interactive selection menu.

### 4. UI-First Discord Control Panel (`cogs/server_manager.py`)
- `/server_manager` (or `/damu`): Main visual dashboard with live stats (members, channels, roles, health).
- **Sub-Managers**:
  - 💬 Channel Manager (Create, Edit, Clone, Move, Permissions, Delete)
  - 📁 Category Manager (Create, Rename, Permissions, Detect Orphans, Delete)
  - 👥 Role Manager (Create, Color/Hoist, Permissions, Delete)
  - 🔐 Permission Manager (Interactive presets and custom permission toggles)
  - 🏗️ Server Builder Wizard (Step-by-step template and module selector)
  - 🔎 Server Analyzer & Smart Fixes

### 5. Server Analyzer & Smart Fix System (`engines/guild/analyzer.py`)
- Read-only diagnostics for:
  - Orphan channels (channels with no parent category)
  - Role hierarchy conflicts
  - Dangerous permission leaks (e.g. `@everyone` having send permissions in announcement channels)
  - Bot permission gaps (`Manage Channels`, `Manage Roles`)
  - Ticket and AutoMod configuration status
- **Smart Fixes**: Displays each detected issue as an isolated preview card with an `[ Apply Fix ]` button. Never auto-modifies servers without confirmation.

### 6. Build Transaction, Diff & Rollback (`engines/builder/`)
- **Diff Engine (`diff.py`)**: Compares current guild state against requested state and renders visual change previews.
- **Transaction Rollback (`rollback.py`)**: Automatically reverts completed operations (deleting created channels/roles) if a multi-step build fails.

### 7. Intelligence & 5-Tier Fallback System (`engines/intelligence/`)
- **Tier 1**: AI Planner (OpenRouter / LLM natural language synthesis)
- **Tier 2**: Fallback AI Model
- **Tier 3**: Deterministic Rule-Based Planner (Regex intent extraction)
- **Tier 4**: Built-in Server Templates (Gaming, Community, Study, Creator, Professional)
- **Tier 5**: Safe Default Configurations
- **AI Safety Validator (`validator.py`)**: Repaired JSON parsing, schema validation, semantic checks, and automatic stripping of dangerous permissions. AI never directly accesses Discord REST endpoints.

### 8. Support Ticket System (`cogs/ticket_system.py`)
- Immediate deferral pattern eliminates 10062 errors.
- Multi-category support (Tech Support, Server Support, Mod Support).
- Ticket claiming, close confirmation dialogs, HTML transcript generation, auto-deletion timers, and blacklist management.
- MongoDB Atlas persistence with an automatic, resilient in-memory fallback.

### 9. Startup & Rate-Limit Recovery Manager (`core/startup/`)
- **Resilient Connection Lifecycle**: Replaces direct unhandled `bot.start()` with `StartupManager`. Eliminates Render restart loops caused by temporary Discord HTTP 429 / Cloudflare Error 1015 bans.
- **Single Connection Guarantee (`lifecycle.py`)**: `ConnectionGuard` enforces an in-process lock preventing duplicate concurrent connection loops.
- **Error Classification (`classifier.py`)**: Distinguishes rate limits (429), invalid tokens (401), permission errors (403), DNS errors, and gateway disconnects. 401 token errors never enter infinite retry loops.
- **Exponential Backoff with Jitter (`backoff.py`)**: Honors `Retry-After` headers with precedence over exponential backoff, applying random jitter and bounded caps.
- **Render Health & Readiness Separation (`health_server.py`)**:
  - `GET /health`: Process health check. Always returns HTTP 200 while the process is alive (even during rate-limiting or reconnecting) to prevent Render restart storms.
  - `GET /ready`: Discord connection readiness. Returns HTTP 200 when Discord is ready, and HTTP 503 when disconnected or recovering.
  - `GET /status`: Diagnostic status payload (state, attempt, uptime) with zero secret exposure.

> [!IMPORTANT]
> **Render Deployment Health Check**: In your Render Dashboard (Service Settings &rarr; Health Check Path), configure the health check endpoint to **`/health`** (do NOT use `/ready` as the primary process health check, otherwise Render will terminate the container during transient Discord rate limits).

### 10. Bot Health & Diagnostics (`engines/health/`)
- `/damu_status`: Real-time operational overview (latency, API status, database, AI, active tasks, error counters).
- `/damu_doctor`: Deep self-diagnostic inspecting bot permissions, database reachability, loaded cogs, persistent views, and storage.

---

## Slash Command Reference

| Command | Description | Permissions |
|---|---|---|
| `/server_manager` | Open the main interactive DAMU server control panel | Administrator |
| `/damu` | Alias for `/server_manager` | Administrator |
| `/server_analyze` | Run read-only server health diagnostics and view suggested fixes | Manage Guild |
| `/damu_status` | View bot status, latency, database, and engine health | Everyone |
| `/damu_doctor` | Run deep self-diagnostics and system checks | Administrator |
| `/setup_tickets` | Deploy the persistent ticket panel to a channel | Manage Guild |
| `/ticket_blacklist add/remove/list` | Manage the ticket blacklist | Manage Guild |
| `/setup_server` | Deploy server architecture from built-in templates | Manage Guild |
| `/generate_server` | Generate server architecture plan from natural language | Manage Guild |
| `/verification_status` | Check button verification status | Manage Guild |

---

## Offline Testing Suite

The test suite runs **100% offline** without requiring a live Discord token, MongoDB instance, or external API keys using complete mock Discord fixtures.

```bash
# Run all tests
python -m pytest -q

# Run specific engine tests
python -m pytest tests/test_interaction.py -v
python -m pytest tests/test_permissions.py -v
python -m pytest tests/test_ticket_flow.py -v
python -m pytest tests/test_channel_engine.py -v
python -m pytest tests/test_category_engine.py -v
python -m pytest tests/test_builder_planner.py -v
python -m pytest tests/test_ai_fallback.py -v
```

### Verified Test Cases
- Interaction already acknowledged vs unacknowledged vs expired
- Ticket creation, duplicate ticket prevention, blacklist, cooldown, and missing category recovery
- Role resolver exact and ambiguous semantic match dialogs
- Channel Engine text/voice/forum creation, editing, deletion, moving, and cloning
- Category Engine creation, renaming, moving, and orphan detection
- Permission Engine presets, overwrites, hierarchy checks, and Administrator warnings
- Multi-step build execution, diff calculation, and rollback
- Rate-limit retry with exponential backoff
- AI JSON repair, validation, and deterministic rule-based fallback

---

## Local Development & Startup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/krishnverma32/damu-server-builder.git
   cd damu-server-builder
   ```

2. **Set up virtual environment:**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Add your `DISCORD_TOKEN` (and optional `MONGO_URI`, `OPENROUTER_API_KEY`).

5. **Validate syntax and compile:**
   ```bash
   python -m compileall .
   ```

6. **Start the bot:**
   ```bash
   python main.py
   ```

---

## Environment Variables

| Variable | Required? | Description |
|---|---|---|
| `DISCORD_TOKEN` | **YES** | Discord Bot Token. |
| `MONGO_URI` | Optional | MongoDB Atlas connection string for ticket and guild memory persistence. In-memory fallback is used if omitted. |
| `OPENROUTER_API_KEY` | Optional | API key for AI server generation and conversational assistant. Deterministic rule fallback is used if omitted. |
| `PORT` | Auto | Port for the keep-alive health server (defaults to `8080` locally, `10000` on Render). |
| `STARTUP_BASE_BACKOFF` | Optional | Initial retry delay in seconds for transient rate limits (default: `5.0`). |
| `STARTUP_MAX_BACKOFF` | Optional | Maximum retry delay cap in seconds (default: `600.0` / 10 minutes). |
| `STARTUP_JITTER` | Optional | Bounded random jitter factor (default: `0.25`). |
| `STARTUP_MAX_ATTEMPTS` | Optional | Maximum retry attempts (`0` for unlimited transient retries). |
| `STARTUP_KEEP_ALIVE_ON_DEGRADED` | Optional | If `true` or running on Render, keeps process alive in degraded mode on fatal config errors. |
| `BOT_PREFIX` | Optional | Prefix for legacy text commands (defaults to `!`). |
| `MOD_LOG_CHANNEL_ID` | Optional | Channel ID for moderation audit logs. |
| `TICKET_LOG_CHANNEL_ID`| Optional | Channel ID for ticket transcripts and audit logs. |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

## Private security and quarantine

The bot uses Discord Components V2 for the command center, security console and compact command results. Existing ticket, shop, JSON and detailed build controls keep their specialized workflows. Install `discord.py>=2.6.0,<3.0` from `requirements.txt`.

| Command | Purpose |
| --- | --- |
| `/create_channel name kind category private` | Create a text channel, voice channel or category. A private channel initially admits its creator, the bot and administrators. |
| `/help` | Open the new DAMU command center. |
| `/server_manager` or `/damu` | Open the existing server manager. |
| `/security` | Open the administrator's private permission and recovery status. |
| `/quarantine_setup staff_role` | Create a hidden category, review channel and marker role, then add restrictions to existing channels. The staff role is optional. Repeat to repair a partial setup. |
| `/quarantine member reason` | Suspend editable roles and channel access, saving a durable recovery record. |
| `/sudo_ban member reason` | Apply the same reversible quarantine. The member stays in the guild. |
| `/quarantine_release member` | Restore saved roles and channel access. Repeat after fixing permissions if release is partial. |
| `/butler status` | Check private reporting and activity collection. |
| `/butler report [date]` | Bot owner only, privately open the activity ledger. |
| `/bot_profile` | Bot application owner only, refresh the dynamic public description and presence. |

Quarantine setup requires Administrator on the caller. Apply/release requires Moderate Members and Manage Roles on the caller, plus the normal actor/target hierarchy checks. The bot needs View Channel, Send Messages, Read Message History, Manage Channels and Manage Roles and must outrank every role it suspends or restores. Existing role order is preserved. The owner is protected. Targets with privileged everyone/managed/uneditable roles are refused. The quarantine marker has zero guild permissions and is neither hoisted nor mentionable. Deleted resources can be recreated by rerunning setup.

Per-member channel overwrites enforce quarantine even where other roles explicitly allow access. Channels created during quarantine and members who leave/rejoin are reconciled. Voice disconnection additionally needs Move Members. Failed restrictions produce a partial result, which can be retried. Roles that gained permissions during quarantine require staff review before restoration. Changes to overwrite fields made independently by staff are preserved on release when they differ from the bot's last applied values.

Timeouts, automatic warning timeouts, kicks, bans, quarantines and releases generate private receipts to both the bot application owner and the server owner. Successful bot actions are recorded in the daily ledger. The original `/ban` remains available for an actual Discord ban. Use `/sudo_ban` for quarantine. Daily bot-owner reports run at **00:05 Asia/Kolkata** by default, with retryable delivery and the first available today's report on startup. Configure `BUTLER_OWNER_ID` for the report recipient and `BUTLER_REPORT_HOUR`/`BUTLER_REPORT_MINUTE` for another local time. DMs must be open.

Moderation command replies are ephemeral. The configured moderation log is skipped when ordinary members can view it. Quarantine spaces are hidden from ordinary members. Server owners and Administrators retain Discord's visibility bypass, and members can still observe role/profile changes. The bot cannot guarantee invisible moderation or stop an owner removing its permissions. New channels created by other clients are protected when Discord delivers their creation events.

`BOT_CREATOR_NAME=luffyanna` supplies the public creator credit. The application description and presence refresh every 15 minutes with the version and server count. Private incident counts stay in private reports. These updates use the application description API, and require a running bot with a valid token.

Keep `data/quarantine.json` and `data/butler.sqlite3` on persistent storage and run one bot process for these local stores. After restart, active records and channel restrictions are reconciled. Partial releases remain recorded for explicit staff completion. Hidden channels are marked incomplete and never used for permission snapshots. Discord API writes span multiple requests, so an interruption can leave a partial operation. Review `/security`, `/butler status` and hosting logs before treating a partial result as complete.

### Wispbyte deployment

This bot’s source is `https://github.com/krishnverma32/damu-server-builder.git`. The startup log identifies DAMU v2.3.0 and prints that repository. The security cog and butler cog must both load before their commands can sync. `/diagnostics` shows extension/sync failures and `/sync_commands` retries registration for the application owner or configured developer.

A custom Wispbyte startup command replaces the normal Auto Update behavior. It must pull this repository before launching the bot. Preserve `.env` and `data/`, and update using a fast-forward pull. A clone-only-if-`main.py`-is-missing command keeps running old files across restarts.
