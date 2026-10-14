import logging
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = commands.Bot(
        command_prefix=commands.when_mentioned,
        intents=intents,
        allowed_mentions=discord.AllowedMentions.none(),
        help_command=None,
    )

    @bot.event
    async def on_ready():
        logger.info("Logged in as %s", bot.user)

    return bot
