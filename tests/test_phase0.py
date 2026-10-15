import dataclasses
import os
import unittest
from unittest.mock import patch

from config import Config
from bot import create_bot
import discord
from discord.ext import commands


class TestPhase0Config(unittest.TestCase):
    def test_config_is_dataclass(self):
        self.assertTrue(dataclasses.is_dataclass(Config))

    def test_config_default_fields(self):
        self.assertIsInstance(Config.model, str)
        self.assertIsInstance(Config.temperature, float)
        self.assertIsInstance(Config.top_p, float)
        self.assertIsInstance(Config.cooldown_seconds, int)
        self.assertIsInstance(Config.max_hours, int)
        self.assertIsInstance(Config.chunk_size, int)
        self.assertIsInstance(Config.max_sections, int)
        self.assertIsInstance(Config.max_body_sentences, int)
        self.assertIsInstance(Config.discord_char_limit, int)
        self.assertIsInstance(Config.summary_target_max_chars, int)
        self.assertIsInstance(Config.single_pass_max_messages, int)
        self.assertIsInstance(Config.max_messages_fetched, int)
        self.assertIsInstance(Config.max_concurrent_llm_calls, int)

    def test_command_prefix_removed(self):
        self.assertFalse(hasattr(Config, "command_prefix"))

    def test_compatibility_aliases(self):
        self.assertEqual(Config.MODEL, Config.model)
        self.assertEqual(Config.DISCORD_TOKEN, Config.discord_token)
        self.assertEqual(Config.GROQ_API_KEY, Config.groq_api_key)
        self.assertEqual(Config.DEV_GUILD_ID, Config.dev_guild_id)

    def test_class_immutability(self):
        with self.assertRaises(TypeError):
            Config.model = "modified-model"

    def test_instance_immutability(self):
        cfg = Config()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.model = "modified-model"

    def test_validate_success_on_valid_tokens(self):
        # Config has tokens loaded from .env in this workspace
        # If both are present, validate() should execute without error
        cfg = Config(discord_token="valid_token", groq_api_key="valid_key")
        cfg.validate()

    def test_validate_fails_on_missing_discord_token(self):
        cfg = Config(discord_token="", groq_api_key="valid_key")
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("DISCORD_TOKEN is missing", str(ctx.exception))

    def test_validate_fails_on_missing_groq_api_key(self):
        cfg = Config(discord_token="valid_token", groq_api_key="")
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("GROQ_API_KEY is missing", str(ctx.exception))

    def test_validate_fails_on_both_missing(self):
        cfg = Config(discord_token="", groq_api_key="")
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        err_msg = str(ctx.exception)
        self.assertIn("DISCORD_TOKEN is missing", err_msg)
        self.assertIn("GROQ_API_KEY is missing", err_msg)

    def test_dev_guild_id_parsing(self):
        from config import _parse_dev_guild_id
        with patch.dict(os.environ, {"DEV_GUILD_ID": "1234567890"}):
            self.assertEqual(_parse_dev_guild_id(), 1234567890)
        with patch.dict(os.environ, {"DEV_GUILD_ID": ""}):
            self.assertIsNone(_parse_dev_guild_id())
        with patch.dict(os.environ, {"DEV_GUILD_ID": "not-an-int"}):
            self.assertIsNone(_parse_dev_guild_id())


class TestPhase0BotAndLogging(unittest.TestCase):
    def test_bot_command_prefix_when_mentioned(self):
        bot = create_bot()
        self.assertEqual(bot.command_prefix, commands.when_mentioned)

    def test_loggers_configured(self):
        import logging
        import main
        import bot
        import utils.messages
        import services.summarizer
        import cogs.tldr

        self.assertIsInstance(main.logger, logging.Logger)
        self.assertIsInstance(bot.logger, logging.Logger)
        self.assertIsInstance(utils.messages.logger, logging.Logger)
        self.assertIsInstance(services.summarizer.logger, logging.Logger)
        self.assertIsInstance(cogs.tldr.logger, logging.Logger)

    def test_no_raw_print_in_source_files(self):
        root_dir = os.path.dirname(os.path.dirname(__file__))
        source_dirs = ["cogs", "services", "utils"]
        source_files = ["main.py", "bot.py", "config.py"]

        all_paths = [os.path.join(root_dir, f) for f in source_files]
        for sdir in source_dirs:
            full_sdir = os.path.join(root_dir, sdir)
            for fname in os.listdir(full_sdir):
                if fname.endswith(".py"):
                    all_paths.append(os.path.join(full_sdir, fname))

        for path in all_paths:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("print(", content, f"Found print() call in {path}")


if __name__ == "__main__":
    unittest.main()
