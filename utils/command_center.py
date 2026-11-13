"""Private Components V2 navigation for the DAMU commands."""
import discord
import config
from services.error_service import respond_error

PAGES = {
    'overview': ('DAMU command center', 'Choose a section to open its command guide.\nCreated by ' + config.BOT_CREATOR_NAME),
    'builder': ('Server builder', '`/server_manager` or `/damu` opens the existing manager.\n`/create_channel` creates one channel.\n`/setup_server` and `/setup_custom` build a layout.\n`/server_analyze` checks the server.'),
    'security': ('Security and quarantine', '`/security` opens private status.\n`/quarantine_setup` creates the review room and role.\n`/quarantine` or `/sudo_ban` suspends access.\n`/quarantine_release` restores saved access.\n`/kick`, `/ban`, `/mute`, `/unmute`, `/lock`, `/unlock` handle moderation.'),
    'reports': ('Private owner reports', '`/butler status` checks collection and delivery.\n`/butler report` opens the bot owner’s ledger.\nDaily reports include joins, departures, voice presence, audit summaries and bot moderation actions.'),
    'community': ('Community tools', '`/setup_tickets` configures tickets.\n`/setupverification` configures verification.\n`/automod_status` opens existing automatic moderation.\n`/ai`, `/rank`, `/poll`, `/send_rules` and `/remind` remain available.'),
    'diagnostics': ('Bot diagnostics', '`/diagnostics` or `/damu_doctor` checks the bot.\n`/sync_commands` retries command registration for the bot owner/developer.\n`/bot_profile` refreshes the public description for the application owner.'),
}


class CommandCenterView(discord.ui.LayoutView):
    def __init__(self, owner_id):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.card = discord.ui.Container(accent_colour=config.BOT_COLOR)
        self.add_item(self.card)
        menu = discord.ui.Select(placeholder='Browse DAMU tools', options=[
            discord.SelectOption(label=title, value=key) for key, (title, _) in PAGES.items()])
        menu.callback = self.choose
        self.add_item(discord.ui.ActionRow(menu))
        self.show('overview')

    def show(self, key):
        title, description = PAGES[key]
        self.card.clear_items()
        self.card.add_item(discord.ui.TextDisplay('## ' + title + '\n' + description))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('This guide belongs to the person who opened it.', ephemeral=True)
            return False
        return True

    async def choose(self, interaction):
        self.show(interaction.data['values'][0])
        await interaction.response.edit_message(view=self)

    async def on_error(self, interaction, error, item):
        await respond_error(interaction, error, context='DAMU command center')
