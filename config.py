import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))


class Config:
    # Tokens
    discord_token = os.getenv("DISCORD_TOKEN")
    groq_api_key = os.getenv("GROQ_API_KEY")

    # Models
    model = "openai/gpt-oss-120b"
    temperature = 0.25
    top_p = 0.9

    # Bot
    command_prefix = "/"
    cooldown_seconds = 30
    max_hours = 24

    # Summarizer
    chunk_size = 200
    max_sections = 12
    max_body_sentences = 999  # Don't slice; let char limit handle it
    discord_char_limit = 2000
    summary_target_max_chars = 5000
    single_pass_max_messages = 300

    # Collection limits
    max_messages_fetched = 5000  # Hard cap per command; avoids unbounded history walks
    max_concurrent_llm_calls = 3
