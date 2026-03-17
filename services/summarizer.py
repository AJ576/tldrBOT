import asyncio
import logging
import random
import time
from groq import Groq
from config import Config
from utils.formatting import sanitize_summary, enforce_tldr_shape
from utils.messages import chunk_messages

log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds
STAGGER_DELAY = 1.5   # seconds between parallel launches
MAX_BACKOFF_SECONDS = 20

PERSONALITY = """\
You are a regular member of this Discord server writing a quick recap.
You mildly roast some users depending on their activites.
Keep it conversational, funny, and meme-aware, but prioritize factual accuracy over style.
Use playful phrasing and occasional witty punchlines."""

FORMAT_RULES = f"""\
- Keep total output under {Config.summary_target_max_chars} characters.
- Each section starts with a short bold heading with an emoji, like: **🔥 The Debate**
- After each heading, write 4 to 6 concise sentences.
- **Bold every person's name** when mentioned.
- One blank line between sections.
- No bullets. No intro line. No conclusion line.
- Keep humor light (small jokes/phrases), never at the expense of factual accuracy.
- Only include claims grounded in the provided conversation.
- Do not invent events, names, or opinions not present in the input."""

MERGE_RULES = f"""\
- Combine partial summaries into ONE cohesive summary.
- Keep total output under {Config.summary_target_max_chars} characters.
- 4 to 6 sections total.
- Each section starts with a short bold heading with an emoji.
- After each heading, write 4 to 6 concise sentences.
- **Bold every person's name** when mentioned.
- One blank line between sections.
- Keep humor light and consistent across sections.
- Merge overlaps and remove repetition.
- Only keep facts supported by the partial summaries."""

_client = Groq(api_key=Config.groq_api_key)


def _is_error_summary(text: str) -> bool:
    return text.startswith("[") and text.endswith("]")


def _call_groq(prompt: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            completion = _client.chat.completions.create(
                model=Config.groq_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=Config.temperature,
                top_p=Config.top_p,
            )
            return completion.choices[0].message.content or ""
        except Exception as e:
            msg = str(e).lower()
            is_transient = any(k in msg for k in ("429", "rate", "timeout", "503", "connection"))
            if is_transient and attempt < MAX_RETRIES - 1:
                base = RETRY_BASE_DELAY * (2 ** attempt)
                delay = min(MAX_BACKOFF_SECONDS, base + random.uniform(0, 0.75))
                log.warning("Groq transient error; retrying in %.2fs (attempt %d/%d)", delay, attempt + 1, MAX_RETRIES)
                time.sleep(delay)
                continue
            log.exception("Groq API request failed")
            return "[Groq API request failed]"
    return "[Groq API request failed]"


def _build_chunk_prompt(text: str) -> str:
    return f"""\
{PERSONALITY}

You're summarizing what just happened in the Discord chat. Write it like you're \
posting the recap in the server yourself — not like a bot, like a PERSON.

Rules (strict):
{FORMAT_RULES}

Conversation:
{text}"""


def _build_merge_prompt(summaries: list[str]) -> str:
    parts = "\n\n---\n\n".join(
        f"**Part {i + 1}:**\n{s}" for i, s in enumerate(summaries)
    )
    return f"""\
{PERSONALITY}

You're merging multiple partial recaps into one final summary. Keep your voice \
consistent — you were there for ALL of it.

Rules (strict):
{MERGE_RULES}

Partial summaries:
{parts}"""


def summarize_chunk(chunk: list[str], compact: bool = False) -> str:
    prompt = _build_chunk_prompt("\n".join(chunk))
    raw = _call_groq(prompt)
    if _is_error_summary(raw):
        return raw
    cleaned = sanitize_summary(raw)
    return enforce_tldr_shape(cleaned) if compact else cleaned


async def summarize_parallel(messages: list[str]) -> str:
    """Fan-out: summarize each chunk with staggered starts, then merge into one summary."""
    if not messages:
        return "[No messages to summarize]"

    # For smaller windows, skip lossy merge and summarize once.
    if len(messages) <= Config.single_pass_max_messages:
        return summarize_chunk(messages, compact=True)

    chunks = list(chunk_messages(messages, chunk_size=Config.chunk_size))
    if not chunks:
        return "[No messages to summarize]"

    if len(chunks) == 1:
        return summarize_chunk(chunks[0], compact=True)

    tasks = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(STAGGER_DELAY)
        tasks.append(asyncio.to_thread(summarize_chunk, chunk, True))

    partial_summaries = await asyncio.gather(*tasks)

    valid = [s.strip() for s in partial_summaries if s and not _is_error_summary(s)]
    if not valid:
        return "[All summarization calls failed]"

    if len(valid) == 1:
        return valid[0]

    merge_prompt = _build_merge_prompt(valid)
    raw = await asyncio.to_thread(_call_groq, merge_prompt)
    if _is_error_summary(raw):
        return raw

    cleaned = sanitize_summary(raw)
    return enforce_tldr_shape(cleaned)


def summarize_full(messages: list[str]) -> str:
    """Sync wrapper — returns multi-part summaries (no merge)."""
    chunks = list(chunk_messages(messages, chunk_size=Config.chunk_size))

    if len(chunks) == 1:
        return summarize_chunk(chunks[0], compact=True)

    parts = []
    for i, chunk in enumerate(chunks):
        summary = summarize_chunk(chunk, compact=True)
        parts.append(f"**🧩 Part {i + 1}**\n{summary}")

    return "\n\n".join(parts)
