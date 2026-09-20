# Damu — Discord Server Platform & Server Builder

A powerful Python Discord bot built with `discord.py` 2.x for designing, building, configuring, securing, and managing Discord servers.

Damu turns complex Discord server setup into a smooth, interactive experience with:
- **Interactive Server Builder**: Create any channel under any category with custom three-state permissions without touching JSON.
- **Natural Language Server Editor**: Describe intended modifications in plain English; AI safely generates structured diff proposals without direct mutation.
- **Templates & Custom JSON**: Shipped templates (Gaming, Community, Study, Business) or custom JSON schemas for full infrastructure-as-code automation.
- **Safe Pipeline**: Every build executes through: `Validate` → `Plan` → `Diff` → `Preview` → `Confirm` → `Execute` → `Rollback`.
- **Server Snapshots & Rollback**: Versioned server backups, one-click restores, and persistent build rollbacks tracked in SQLite.
- **Security Audit & Guided Remediation**: Automatic scans for bot role hierarchy, exposed `@everyone` permissions, unmanaged channels, and one-click fixes.
- **Unified Command Center**: Interactive `/dashboard` for managing Builder, Permissions, Roles, AutoMod, Verification, Tickets, and Moderation.

---

## Defining Workflow

```text
USER REQUEST (Interactive UI / JSON / AI)
     ↓
SERVER CONFIG
     ↓
VALIDATION (JSON Schema & Discord Limits)
     ↓
PERMISSION ANALYSIS (Three-State: Allow / Deny / Inherit)
     ↓
CONFLICT DETECTION (Hierarchy, Duplicates, Limits)
     ↓
DETERMINISTIC DIFF (Create, Reuse, Update, Delete)
     ↓
INTERACTIVE PREVIEW ([Build] [Edit] [Permissions] [Diff] [Cancel])
     ↓
ADMINISTRATOR CONFIRMATION
     ↓
BUILD ENGINE (Auto-assigned Build #ID & Progress Bar)
     ↓
AUDIT LOG & PERSISTENT HISTORY
```

---

## Setup & Quickstart

### 1. Requirements

- Python 3.10, 3.11, 3.12, 3.13, or 3.14
- Discord Bot Token with Server Members Intent & Message Content Intent enabled in the Discord Developer Portal

### 2. Installation

```bash
git clone https://github.com/krishnverma32/damu-server-builder.git
cd damu-server-builder
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file based on `.env.example`:

```env
# Required
DISCORD_TOKEN=your_bot_token_here
BOT_OWNER_ID=486555340670894080
SERVER_BUILD_OWNER_ID=486555340670894080

# Optional
DATABASE_FILE=data/bot.db
OPENROUTER_API_KEY=your_openrouter_api_key_here
GIPHY_API_KEY=your_giphy_api_key_here
```

| Variable | Description | Required | Default |
| :--- | :--- | :--- | :--- |
| `DISCORD_TOKEN` | Discord bot application token | **Yes** | — |
| `BOT_OWNER_ID` | Discord user ID of the primary bot administrator | **Yes** | — |
| `SERVER_BUILD_OWNER_ID` | Discord user ID authorized to manage builder bypass | **Yes** | — |
| `DATABASE_FILE` | Path to the SQLite persistence database | No | `data/bot.db` |
| `OPENROUTER_API_KEY` | OpenRouter API key for Gemini / AI chat & AI server editor | No | Empty |
| `GIPHY_API_KEY` | Giphy API key for automated welcome GIFs | No | Empty |

### 4. Running the Bot

```bash
# Windows
py main.py

# Linux / macOS
python3 main.py
```

To sync slash commands to your test server:
```text
/sync guild
```

---

## Commands Reference

### 🏗️ Interactive Server Builder

| Command | Permissions | Description & Examples |
| :--- | :--- | :--- |
| `/dashboard` | Administrator | Interactive management center across all bot modules |
| `/create_channel` | Manage Channels | Step-by-step UI to create Text, Voice, Forum, Stage, or Announcement channels under any category |
| `/create_category` | Manage Channels | Create a category with permission presets and quick-add channel flow |
| `/channel_permissions` | Manage Roles | Interactive 3-state permission editor (`Allow`, `Deny`, `Inherit`) for any channel |
| `/permission_matrix` | Manage Roles | Visual matrix grid comparing roles vs key permissions (`View`, `Send`, `Files`, `Embed`, `Manage`) |
| `/clone_channel` | Manage Channels | Duplicate a channel with all overwrites, topics, slowmodes, and tags |
| `/clone_category` | Manage Channels | Duplicate an entire category and all of its contained channels |
| `/create_role` | Manage Roles | Create a role with presets (`Admin`, `Moderator`, `VIP`, `Support`, `Creator`...) and hierarchy validation |
| `/edit_role` | Manage Roles | Modify role name, color, hoist, and mentionable settings safely |
| `/delete_role` | Manage Roles | Delete a role with hierarchy check protection |

### 🚀 Templates & Full Builds

| Command | Permissions | Description |
| :--- | :--- | :--- |
| `/setup_server` | Administrator | Build from curated templates (`gaming`, `community`, `study`, `business`) |
| `/setup_custom` | Administrator | Build from an attached `.json` file or pasted text |
| `/setup_paste_json` | Administrator | Open a Discord modal to paste JSON and build |
| `/build_preview` | Administrator | Side-effect-free preflight check showing required actions, warnings, and diff |
| `/server_templates` | Everyone | Browse summaries and channel counts of bundled templates |
| `/template_details` | Everyone | View detailed roles, categories, and channels of a template |
| `/example_template` | Everyone | Download an editable example JSON template |
| `/server_json` | Everyone | Export schema definition or template JSON |
| `/perm_sync_check` | Administrator | Verify live server permissions against template / last build JSON |

### 💾 Snapshots, Export, Import & Rollback

| Command | Permissions | Description |
| :--- | :--- | :--- |
| `/server_snapshot` | Administrator | Capture a versioned backup of all roles, categories, channels, and permissions |
| `/snapshot_list` | Administrator | List all saved snapshots for the server |
| `/snapshot_restore` | Administrator | Restore a layout safely through preflight preview and build engine |
| `/server_export` | Administrator | Download complete server structure as a clean JSON file (no secrets) |
| `/server_import` | Administrator | Upload an exported JSON file, inspect diff, and build safely |
| `/build_history` | Administrator | View past server builds recorded with auto-assigned `Build #ID`s |
| `/build_rollback` | Administrator | Roll back resources created by a specific build ID without affecting other resources |

### 🛡️ Security Audit & Server Fix

| Command | Permissions | Description |
| :--- | :--- | :--- |
| `/server_audit` | Administrator | Comprehensive security scan: bot hierarchy, `@everyone` privileges, log channels |
| `/server_fix` | Administrator | Safe guided remediation for detected security vulnerabilities |

### 🤖 AI Natural Language Editor

| Command | Permissions | Description |
| :--- | :--- | :--- |
| `/ai_edit_server` | Administrator | Plain English instructions (e.g. *"Make #announcements read-only"*, *"Add a private staff category"*) translated into validated diff proposals |
| `/generate_server` | Administrator | AI generates an entire themed server schema from a prompt |
| `/ai chat` | Everyone | OpenRouter conversational assistant with per-user budgets |

---

## Permission Modeling

### Three-State Channel Overwrites

Discord permission inheritance relies on three states:
- **`Allow` (`True`)**: Explicitly grant permission.
- **`Deny` (`False`)**: Explicitly deny permission.
- **`Inherit / Neutral` (`None`)**: Inherit permission from the category or default server role.

```text
#media
@everyone    View: ✅ Allow | Send: ✅ Allow | Attach Files: ➖ Inherit
@VIP         View: ✅ Allow | Send: ✅ Allow | Attach Files: ✅ Allow
```

### Permission Presets

Built-in presets configurable via dropdown in `/create_channel`, `/create_category`, and `/channel_permissions`:
- **Public Chat**: View, send, history, reactions enabled; mention everyone disabled.
- **Read Only**: View and history enabled; send messages and threads disabled.
- **Announcement**: Public read-only; Moderator & Admin send and mention enabled.
- **Staff Only**: `@everyone` view denied; Staff, Moderator, Admin allowed.
- **Admin Only**: Restricted strictly to Admin roles.
- **VIP Only**: `@everyone` denied; VIP allowed media and chat.
- **Media**: Image attachments, embed links, reactions enabled.
- **Support**: Public read/send; Support role manage messages enabled.
- **Voice Members**: Connect and speak enabled; mute and move disabled.

---

## Hierarchy Validation & Safety

Before executing role modifications, channel updates, or member actions, Damu validates:
1. **Bot Role Position**: Ensures Damu's role is positioned higher than the target role.
2. **User Hierarchy**: Prevents administrators from modifying roles higher than their own.
3. **Managed & Default Roles**: Protects `@everyone` and bot integration roles from invalid mutation.
4. **AI Mutation Guard**: AI can only propose configuration deltas; execution is strictly handled by the deterministic engine after human review.

---

## Testing & Continuous Integration

Run the comprehensive test suite locally:

```bash
# Bytecode compilation check
python -m compileall -q main.py config.py cogs services builder utils tests

# Run unit tests
pytest -v
```

GitHub Actions automatically validates linting, compilation, and unit tests on every push and pull request.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
