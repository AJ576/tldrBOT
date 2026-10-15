import asyncio
import logging
import random
import time
from groq import Groq
from config import Config
from utils.formatting import sanitize_summary, enforce_tldr_shape
from utils.messages import chunk_messages

log = logging.getLogger(__name__)
logger = log

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds
MAX_BACKOFF_SECONDS = 20

PERSONALITY = """\
You're an active member of this Discord server posting a recap.
Sound casual, clear, and mildly funny.
Use light jokes/sarcasm occasionally, but NEVER invent facts, motives, outcomes, or relationships."""

FORMAT_RULES = f"""\
- Keep it under {Config.summary_target_max_chars} characters.
- Strictly follow timeline order from earliest to latest.
- Write 4 to 6 sections.
- Each section starts with a short bold heading + emoji, like: **🔥 Chaos Arc**
- Then write 3 to 6 sentences in normal paragraph style.
- Bold usernames like **name** when mentioned.
- One blank line between sections.
- No bullet points.
- Add mild humor and tiny jokes naturally (no forced comedy).
- Factual accuracy is mandatory.
- If unsure about a detail, omit it."""

MERGE_RULES = f"""\
- Merge all partial summaries into one final recap.
- Keep it under {Config.summary_target_max_chars} characters.
- Preserve chronological flow strictly: Part 1 -> Part 2 -> ...
- Do NOT regroup by topic if that breaks order.
- 4 to 6 sections total.
- Bold heading + emoji for each section.
- 3 to 6 sentences per section.
- Keep tone playful with mild humor.
- Remove repetition.
- If uncertain, omit."""

MAX_FACTCHECK_EVIDENCE_CHARS = 12000

_groq_client = Groq(api_key=Config.groq_api_key) if Config.groq_api_key else None

# Bounds how many chunk summaries hit the API at once, so a large window
# doesn't fire every chunk simultaneously and trip rate limits.
_llm_semaphore = asyncio.Semaphore(Config.max_concurrent_llm_calls)


def _is_error_summary(text: str) -> bool:
    return bool(text) and text.startswith("[") and text.endswith("]")


def _is_transient_error(msg: str) -> bool:
    msg = (msg or "").lower()
    return any(k in msg for k in ("429", "rate", "timeout", "503", "connection", "unavailable"))


def _call_groq(prompt: str) -> str:
    """Send a prompt to Groq, retrying transient failures with backoff."""
    if _groq_client is None:
        return "[LLM unavailable: GROQ_API_KEY is not configured]"

    for attempt in range(MAX_RETRIES):
        try:
            completion = _groq_client.chat.completions.create(
                model=Config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=Config.temperature,
                top_p=Config.top_p,
            )
            text = (completion.choices[0].message.content or "").strip()
            if text:
                return text
            raise RuntimeError("Empty Groq response")
        except Exception as e:
            msg = str(e)
            if _is_transient_error(msg) and attempt < MAX_RETRIES - 1:
                base = RETRY_BASE_DELAY * (2 ** attempt)
                delay = min(MAX_BACKOFF_SECONDS, base + random.uniform(0, 0.75))
                log.warning("Groq transient error; retrying in %.2fs", delay)
                time.sleep(delay)
                continue
            log.exception("Groq API request failed")
            return "[Groq request failed]"
    return "[Groq request failed]"


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


async def summarize_chunk_async(chunk: list[str], compact: bool = False) -> str:
    """Run summarize_chunk off the event loop, no more than N at a time."""
    async with _llm_semaphore:
        return await asyncio.to_thread(summarize_chunk, chunk, compact)


def summarize_chunk(chunk: list[str], compact: bool = False) -> str:
    logger.info("[ai] sending chunk messages=%d compact=%s", len(chunk), compact)
    prompt = _build_chunk_prompt("\n".join(chunk))
    raw = _call_groq(prompt)
    logger.info("[ai] received chunk chars=%d", len(raw or ""))
    if _is_error_summary(raw):
        return raw
    cleaned = sanitize_summary(raw)
    return enforce_tldr_shape(cleaned) if compact else cleaned


def _build_factcheck_prompt(summary: str, messages: list[str]) -> str:
    evidence = "\n".join(messages)
    if len(evidence) > MAX_FACTCHECK_EVIDENCE_CHARS:
        evidence = evidence[-MAX_FACTCHECK_EVIDENCE_CHARS:]  # keep latest context

    return f"""\
You are a strict fact-check editor.

Task:
Rewrite the summary so every claim is supported by the evidence chat log.
If a claim is not clearly supported, delete or soften it.
Do not add new facts.
Keep the same overall structure and tone.

Evidence chat log:
{evidence}

Draft summary:
{summary}
"""


def _fact_check_summary(summary: str, messages: list[str]) -> str:
    raw = _call_groq(_build_factcheck_prompt(summary, messages))
    if _is_error_summary(raw):
        return summary
    return raw.strip() or summary


async def summarize_parallel(messages: list[str]) -> str:
    """Fan-out: summarize chunks with bounded concurrency, then merge into one summary."""
    logger.info("[ai] summarize_parallel start total_messages=%d", len(messages))
    if not messages:
        return "[No messages to summarize]"

    # For smaller windows, skip lossy merge and summarize once.
    if len(messages) <= Config.single_pass_max_messages:
        first = await summarize_chunk_async(messages, compact=True)
        # checked = await asyncio.to_thread(_fact_check_summary, first, messages)
        # return enforce_tldr_shape(sanitize_summary(checked))
        return enforce_tldr_shape(sanitize_summary(first))

    chunks = list(chunk_messages(messages, chunk_size=Config.chunk_size))
    if not chunks:
        return "[No messages to summarize]"

    if len(chunks) == 1:
        return await summarize_chunk_async(chunks[0], compact=True)

    partial_summaries = await asyncio.gather(
        *(summarize_chunk_async(chunk, True) for chunk in chunks)
    )

    valid = [s.strip() for s in partial_summaries if s and not _is_error_summary(s)]
    if not valid:
        return "[All summarization calls failed]"

    if len(valid) == 1:
        return valid[0]

    merge_prompt = _build_merge_prompt(valid)
    logger.info("[ai] merge send partials=%d", len(valid))
    raw = await asyncio.to_thread(_call_groq, merge_prompt)
    logger.info("[ai] merge received chars=%d", len(raw or ""))
    logger.debug("[ai] ready for next")
    if _is_error_summary(raw):
        return raw

    cleaned = sanitize_summary(raw)
    shaped = enforce_tldr_shape(cleaned)
    # checked = await asyncio.to_thread(_fact_check_summary, shaped, messages)
    # return enforce_tldr_shape(sanitize_summary(checked))
    return shaped


def summarize_full(messages: list[str]) -> str:
    """Sync wrapper — returns multi-part summaries (no merge)."""
    chunks = list(chunk_messages(messages, chunk_size=Config.chunk_size))

    if len(chunks) == 1:
        return summarize_chunk(chunks[0], compact=True)

    parts = []
    for i, chunk in enumerate(chunks):
        summary = summarize_chunk(chunk, compact=True)
        # checked = _fact_check_summary(summary, chunk)
        # parts.append(f"**🧩 Part {i + 1}**\n{enforce_tldr_shape(sanitize_summary(checked))}")
        parts.append(f"**🧩 Part {i + 1}**\n{enforce_tldr_shape(sanitize_summary(summary))}")

    return "\n\n".join(parts)
