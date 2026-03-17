from bot import create_bot
from config import Config


async def load_cogs(bot):
    await bot.load_extension("cogs.tldr")


def run():
    bot = create_bot()
    bot.setup_hook = lambda: load_cogs(bot)
    bot.run(Config.discord_token)


if __name__ == "__main__":
    run()
