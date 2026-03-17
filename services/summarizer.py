import asyncio
import logging
import time
from groq import Groq
from config import Config
from utils.formatting import sanitize_summary, enforce_tldr_shape
from utils.messages import chunk_messages

log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds
STAGGER_DELAY = 1.5   # seconds between parallel launches

PERSONALITY = """\
You are a long-time member of this Discord server. You've seen it all. You talk like \
you're IN the group — roasting people, hyping moments, picking sides in arguments, \
and reacting like a friend who was there the whole time. You have opinions. You take \
sides. You're dramatic about dumb things and dismissive about serious things. \
Think of yourself as the server's chaotic narrator — part gossip columnist, part \
hype man, part disappointed parent."""

FORMAT_RULES = """\
- 200 to 400 words. MUST stay under 2000 characters total.
- 4 to 6 sections max.
- Each section: a short bold heading with an emoji, like: **🔥 The Beef Was Real**
- After each heading, write 2 to 4 punchy sentences. Short. Conversational. Not formal.
- **Bold every person's name** when mentioned, like **Aditya** or **dabi**.
- One blank line between sections.
- No bullets. No intro line. No conclusion line. No "in conclusion" energy.
- Use Discord vibes: say things like "ngl", "bro", "respectfully", "lowkey", "deadass".
- Throw in reactions like you were watching it happen: "I can't with this man 💀"
- If someone did something embarrassing, call it out. If something was wholesome, gas it up.
- Roast where appropriate. Hype where earned. Be specific — don't be generic."""

MERGE_RULES = """\
- Combine the partial summaries into ONE cohesive summary.
- 200 to 400 words. MUST stay under 2000 characters total.
- 4 to 6 sections total (not per part).
- Each section: a short bold heading with an emoji, like: **🔥 Some Heading**
- After each heading, write 2 to 4 punchy sentences.
- **Bold every person's name** when mentioned.
- One blank line between sections.
- No bullets. No intro line. No conclusion line.
- Merge overlapping topics. Don't repeat the same event twice.
- Keep the same chaotic narrator energy — you were there for all of it."""

_client = Groq(api_key=Config.groq_api_key)


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
            is_rate_limit = "429" in str(e) or "rate" in str(e).lower()
            if is_rate_limit and attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                log.warning("Rate limited, retrying in %ss (attempt %d/%d)", delay, attempt + 1, MAX_RETRIES)
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
    if raw.startswith("["):
        return raw
    cleaned = sanitize_summary(raw)
    return enforce_tldr_shape(cleaned) if compact else cleaned


async def summarize_parallel(messages: list[str]) -> str:
    """Fan-out: summarize each chunk with staggered starts, then merge into one summary."""
    chunks = list(chunk_messages(messages))

    if len(chunks) == 1:
        return summarize_chunk(chunks[0], compact=True)

    # Staggered fan-out — delay between launches to avoid rate limits
    loop = asyncio.get_running_loop()
    tasks = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(STAGGER_DELAY)
        tasks.append(loop.run_in_executor(None, summarize_chunk, chunk, True))

    partial_summaries = await asyncio.gather(*tasks)

    # Filter out failures
    valid = [s for s in partial_summaries if not s.startswith("[")]
    if not valid:
        return "[All summarization agents failed]"

    # Single chunk survived — return it directly
    if len(valid) == 1:
        return valid[0]

    # Merge — one final call to combine all partial summaries
    merge_prompt = _build_merge_prompt(valid)
    raw = _call_groq(merge_prompt)
    if raw.startswith("["):
        return raw
    cleaned = sanitize_summary(raw)
    return enforce_tldr_shape(cleaned)


def summarize_full(messages: list[str]) -> str:
    """Sync wrapper — returns multi-part summaries (no merge)."""
    chunks = list(chunk_messages(messages))

    if len(chunks) == 1:
        return summarize_chunk(chunks[0], compact=True)

    parts = []
    for i, chunk in enumerate(chunks):
        summary = summarize_chunk(chunk, compact=True)
        parts.append(f"**🧩 Part {i + 1}**\n{summary}")

    return "\n\n".join(parts)
