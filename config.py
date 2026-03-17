import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))


class Config:
    # Tokens
    discord_token = os.getenv("DISCORD_TOKEN")
    groq_api_key = os.getenv("GROQ_API_KEY")

    # Model
    groq_model = "llama-3.1-8b-instant"
    temperature = 0.5
    top_p = 0.9

    # Bot
    command_prefix = "/"
    cooldown_seconds = 30
    max_hours = 720

    # Summarizer
    chunk_size = 200
    max_sections = 8
    max_body_sentences = 999  # Don't slice; let char limit handle it
    discord_char_limit = 2000
    summary_target_max_chars = 5000
    single_pass_max_messages = 300
