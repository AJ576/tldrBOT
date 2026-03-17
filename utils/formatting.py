import re
import discord
from config import Config


def sanitize_summary(text: str) -> str:
    if not text:
        return text

    text = re.sub(
        r"^\s*(welcome to|here's|in this|buckle up|behold)[^.!?\n]*[.!?]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^\s*(final tldr|tldr)\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def enforce_tldr_shape(text: str, max_sections: int = Config.max_sections) -> str:
    if not text:
        return text

    text = text.replace("\r\n", "\n").strip()
    sections = [s.strip() for s in re.split(r"\n\s*\n+", text) if s.strip()]

    cleaned = []
    for section in sections[:max_sections]:
        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        if not lines:
            continue

        heading = lines[0]
        body = " ".join(lines[1:]).strip()

        if not re.match(r"^\*\*.*\*\*$", heading):
            heading = f"**{heading.strip(':')}**"

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
        body = " ".join(sentences[:Config.max_body_sentences]).strip()

        cleaned.append(f"{heading}\n{body}" if body else heading)

    return "\n\n".join(cleaned).strip()


async def send_long_message(target, text):
    for i in range(0, len(text), Config.discord_char_limit):
        await target.send(
            text[i:i + Config.discord_char_limit],
            allowed_mentions=discord.AllowedMentions.none(),
        )
