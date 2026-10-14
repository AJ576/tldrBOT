from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))


def _parse_dev_guild_id() -> int | None:
    raw = os.getenv("DEV_GUILD_ID")
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


class _ConfigMeta(type):
    def __setattr__(cls, name, value):
        if getattr(cls, "_frozen", False):
            raise TypeError(f"Config is immutable; cannot modify attribute {name!r}")
        super().__setattr__(name, value)


class _ValidateDescriptor:
    def __get__(self, instance, owner):
        target = instance if instance is not None else owner

        def _validate() -> None:
            errors = []
            discord_token = getattr(target, "discord_token", "") or ""
            groq_api_key = getattr(target, "groq_api_key", "") or ""
            if not str(discord_token).strip():
                errors.append("DISCORD_TOKEN is missing or empty. Please set it in your environment or .env file.")
            if not str(groq_api_key).strip():
                errors.append("GROQ_API_KEY is missing or empty. Please set it in your environment or .env file.")
            if errors:
                raise ValueError("\n".join(errors))

        return _validate


@dataclass(frozen=True)
class Config(metaclass=_ConfigMeta):
    # Tokens
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")

    # Models
    model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    temperature: float = 0.25
    top_p: float = 0.9

    # Bot
    cooldown_seconds: int = 30
    max_hours: int = 24
    dev_guild_id: int | None = _parse_dev_guild_id()

    # Summarizer
    chunk_size: int = 200
    max_sections: int = 12
    max_body_sentences: int = 999  # Don't slice; let char limit handle it
    discord_char_limit: int = 2000
    summary_target_max_chars: int = 5000
    single_pass_max_messages: int = 300

    # Collection limits
    max_messages_fetched: int = 5000  # Hard cap per command; avoids unbounded history walks
    max_concurrent_llm_calls: int = 3

    # Compatibility aliases
    DISCORD_TOKEN: str = discord_token
    GROQ_API_KEY: str = groq_api_key
    MODEL: str = model
    DEV_GUILD_ID: int | None = dev_guild_id

    validate = _ValidateDescriptor()


Config._frozen = True
