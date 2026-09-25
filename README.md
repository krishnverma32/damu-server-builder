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

### 9. Bot Health & Diagnostics (`engines/health/`)
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
| `BOT_PREFIX` | Optional | Prefix for legacy text commands (defaults to `!`). |
| `MOD_LOG_CHANNEL_ID` | Optional | Channel ID for moderation audit logs. |
| `TICKET_LOG_CHANNEL_ID`| Optional | Channel ID for ticket transcripts and audit logs. |

---

## License

MIT License. See [LICENSE](LICENSE) for details.
