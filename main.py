import logging
from bot import create_bot
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


async def load_cogs(bot):
    await bot.load_extension("cogs.tldr")
    logger.info("Syncing app commands...")
    synced = await bot.tree.sync()
    logger.info("Synced %d app command(s)", len(synced))


def run():
    Config.validate()
    bot = create_bot()
    bot.setup_hook = lambda: load_cogs(bot)
    logger.info("Starting bot...")
    bot.run(Config.discord_token)


if __name__ == "__main__":
    run()
