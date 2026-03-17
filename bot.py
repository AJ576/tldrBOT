import discord
from discord.ext import commands
from config import Config


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(
        command_prefix=Config.command_prefix,
        intents=intents,
        allowed_mentions=discord.AllowedMentions.none(),
        help_command=None,
    )

    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user}")

    return bot
