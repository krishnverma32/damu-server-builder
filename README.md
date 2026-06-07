# Damu Server Builder

A Python Discord bot built with `discord.py` 2.x for building, securing, and managing Discord servers. It includes a server builder, AI assistant, tickets, verification, automod, moderation, welcome/dashboard tools, analytics, leveling, and utility commands.

The bot is Python-only. Old Next.js scaffold files were removed so contributors can focus on the Discord bot code.

## Features

- **Server Builder**: Build channels, categories, forums, roles, permissions, verification areas, and server icons from JSON templates or AI-generated schemas.
- **AI Chat**: OpenRouter-powered assistant with personas, memory, cooldowns, per-user token budgets, global token guard, and per-server AI toggle.
- **Ticket System**: Support tickets with buttons, blacklist controls, transcript generation, staff notifications, and ticket setup commands.
- **Verification**: Automated verified/unverified roles, verification channel setup, persistent verify button, account age checks, and logs.
- **AutoMod**: Link and attachment spam protection, repeated-image detection across channels, exception roles/channels, warnings, timeouts, and owner alerts.
- **Moderation**: Kick, ban, unban, mute, unmute, clear messages, warnings, slowmode, lock, and unlock commands.
- **Dashboard**: Welcome embeds, welcome images/GIFs, auto roles for humans/bots, commands channel setup, mass role management, and server status.
- **Analytics**: Message, command, and member activity tracking with summary commands.
- **Leveling**: Message XP, rank cards, level-up notifications, and admin XP controls.
- **Utility**: Ping, uptime, bot/server/user/role info, avatar/banner, invite, polls, reminders, and rules embeds.
- **Admin**: Owner-only slash command sync, cog reloads, cog status, and shutdown.

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/krishnverma32/damu-server-builder.git
   cd damu-server-builder
   ```

2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file:

   ```env
   DISCORD_TOKEN=your_discord_bot_token
   OPENROUTER_API_KEY=your_openrouter_api_key
   GIPHY_API_KEY=your_giphy_api_key
   BOT_OWNER_ID=486555340670894080
   SERVER_BUILD_OWNER_ID=486555340670894080
   DATABASE_FILE=data/bot.db
   ```

4. Run the bot:

   ```bash
   python main.py
   ```

   On Windows you can also use:

   ```bat
   start_bot.bat
   ```

5. Sync slash commands when needed:

   ```text
   /sync guild
   ```

   Use `/sync global` only when you are ready to update production commands.

## Data Migration

The bot now uses SQLite for core state. To migrate old JSON memory, XP, and ticket data:

```bash
python scripts/migrate_json_to_sqlite.py
```

The script uses upserts, so it is safe to run more than once.

## Project Structure

```text
main.py                     Bot entry point, keep-alive server, cog loader
config.py                   Environment configuration and constants
requirements.txt            Python dependencies
Procfile                    Render deployment command
runtime.txt                 Python runtime hint
start_bot.bat               Windows start helper
stop_bot.bat                Windows stop helper
cogs/                       Slash command modules
  admin.py                  Owner-only sync/reload/shutdown commands
  ai.py                     AI chat, usage limits, personas, toggles
  analytics.py              Server analytics commands
  automod.py                Spam/link/attachment protection
  dashboard.py              Welcome, auto-role, command channel, mass roles
  leveling.py               XP and rank commands
  moderation.py             Moderation commands
  server_builder.py         Server JSON/template builder
  ticket_system.py          Ticket panel and ticket management
  utility.py                Utility and rules commands
  verification.py           Verification setup and verify buttons
services/                   Business logic and persistence helpers
  ai_service.py             OpenRouter integration and AI memory
  database.py               Async SQLite helper
  embed_service.py          Shared embed factory
  json_builder.py           Server schema parsing/building
  level_service.py          SQLite-backed XP service
  permission_service.py     Permission sync and checks
  ticket_service.py         SQLite-backed ticket service
utils/                      Shared helpers
  decorators.py             Command checks
  helpers.py                Text/time/helper utilities
  logger.py                 Logging setup
  paginator.py              Pagination views
scripts/                    Maintenance scripts
  cleanup_nextjs.sh         Removes old Next.js scaffold files
  migrate_json_to_sqlite.py Migrates old JSON state into SQLite
data/                       Runtime SQLite/JSON data, ignored by Git
```

## Commands

### Server Builder

- `/setup_server`: Build or preview a server from a template or JSON.
- `/server_template_list`: List available server templates.
- `/server_template_detail`: Show detailed template contents.
- `/server_json_example`: Send a copyable example JSON schema.
- `/server_builder_bypass_add`: Allow another user to build servers without approval.
- `/server_builder_bypass_remove`: Remove a bypass user.
- `/perm_sync`: Check or repair permissions after a build.

### AI

- `/ai chat`: Chat with the AI assistant.
- `/ai reset`: Clear your AI memory.
- `/ai persona`: Change the assistant persona.
- `/ai usage`: Show your remaining daily AI token budget.
- `/ai stats`: Show server AI usage today.
- `/ai toggle`: Enable or disable AI commands for the server.

### Tickets

- `/setup_tickets`: Configure the ticket panel.
- `/cancel_delete`: Cancel auto-delete for the current ticket channel.
- Ticket buttons: create, claim, close, and transcript workflows.
- `/ticket_blacklist add`, `/ticket_blacklist remove`, `/ticket_blacklist list`: Manage blocked users.

### Verification

- `/setupverification`: Create or edit the verification system.
- `/verification_status`: Show verification configuration.

### AutoMod

- `/automod_status`: Show AutoMod settings and recent offenses.
- `/automod_exception`: Add, remove, or list exception roles/channels.
- `/automod_reset`: Clear a member's AutoMod offenses.

### Dashboard

- `/welcome_setup`: Configure welcome embeds, images, and GIFs.
- `/autorole_setup`: Configure human and bot auto roles.
- `/commands_channel_setup`: Set the bot commands channel.
- `/mass_role`: Give or remove a role from all members, bots, or humans.
- `/dashboard_status`: Show server dashboard settings.

### Moderation

- `/kick`, `/ban`, `/unban`
- `/mute`, `/unmute`
- `/clear`
- `/warn`, `/warnings`, `/clearwarnings`
- `/slowmode`, `/lock`, `/unlock`

### Leveling

- `/rank`: View a rank card.
- `/setxp`: Set a member's XP.

### Analytics

- `/analytics messages`: Show messages per day for the last 7 days.
- `/analytics members`: Show join and leave trends.
- `/analytics commands`: Show most-used commands.

### Utility

- `/ping`, `/uptime`, `/botinfo`
- `/serverinfo`, `/userinfo`, `/roleinfo`
- `/avatar`, `/banner`, `/invite`
- `/poll`, `/remind`
- `/send_rules`: Send a rules embed with an optional uploaded image.

### Admin

- `/sync`: Manually sync slash commands.
- `/reload`: Reload one cog or all cogs.
- `/cogs`: Show loaded and failed cogs.
- `/shutdown`: Gracefully stop the bot.

## Contributing

Use the existing cog/service/utils pattern:

- Put Discord slash commands and event listeners in `cogs/`.
- Put reusable business logic and persistence code in `services/`.
- Put small generic helpers in `utils/`.
- Keep command responses embed-based using `services/embed_service.py`.
- Keep runtime data inside `data/`, which is ignored by Git.
- Run `python -m compileall -q main.py config.py cogs services utils scripts` before committing Python changes.

## License

MIT
