import discord
from discord.ext import commands
import google.generativeai as genai
from datetime import datetime, timedelta
import os
from pathlib import Path
from dotenv import load_dotenv
import re
import traceback



load_dotenv(dotenv_path=Path(__file__).with_name(".env"))
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-flash-lite")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none(),  # prevents @everyone/@here/user/role pings
)

async def get_messages(channel, hours=6, command_message_id=None, include_bots=False):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    messages = []

    async for msg in channel.history(limit=2000, after=cutoff):
        if (not include_bots) and msg.author.bot:
            continue
        if command_message_id and msg.id == command_message_id:
            continue
        content = msg.content.strip()
        if not content:
            continue
        messages.append(f"{msg.author.display_name}: {content}")

    return messages


def chunk_messages(messages, chunk_size=200):
    for i in range(0, len(messages), chunk_size):
        yield messages[i:i + chunk_size]


def sanitize_summary(text: str) -> str:
    if not text:
        return text

    # Remove cliché opener if model still adds it
    text = re.sub(
        r"^\s*(welcome to|here's|in this|buckle up|behold)[^.!?\n]*[.!?]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()


def enforce_tldr_shape(text: str, max_paragraphs: int = 5) -> str:
    """
    Keep single TLDR readable:
    - max 5 paragraphs
    - each paragraph short-ish
    """
    if not text:
        return text

    # Remove markdown headings/bullets if model adds them
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"^\s*(#{1,6}\s*|\-+\s*|\*\s+|\d+\.\s+)", "", ln).strip()
        if ln:
            lines.append(ln)
    text = "\n".join(lines)

    # Split paragraphs (or fallback to sentence chunks)
    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if len(paras) <= 1:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        paras = []
        buf = []
        for s in sentences:
            buf.append(s)
            if len(buf) >= 3:  # ~3 sentences per paragraph
                paras.append(" ".join(buf))
                buf = []
        if buf:
            paras.append(" ".join(buf))

    # Limit sentences per paragraph
    trimmed_paras = []
    for p in paras[:max_paragraphs]:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
        trimmed_paras.append(" ".join(sents[:4]))  # max 4 sentences each

    out = "\n\n".join(trimmed_paras).strip()


    return out


def summarize_chunk(chunk, compact: bool = False):
    text = "\n".join(chunk)

    extra_rules = ""
    if compact:
        extra_rules = """
- Output ONLY 3 to 5 short paragraphs.
- Each paragraph should be 4-6 short sentences.
- Keep it concise and readable.
"""

    prompt = f"""
You are summarizing a Discord chat.

Rules (strict):
- Be humorous/sarcastic.
- DO NOT start with scene-setting phrases like "Welcome to...", "In this...", "Here's...".
- Start immediately with content.
{extra_rules}

Conversation:
{text}
"""
    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.7, "top_p": 0.9},
        )
        cleaned = sanitize_summary(response.text or "")
        if compact:
            return enforce_tldr_shape(cleaned, max_paragraphs=5)
        return cleaned
    except Exception:
        return "[Gemini API limit reached or request failed]"


def summarize_full(messages):
    chunks = list(chunk_messages(messages))
    summaries = []

    # Single chunk → just one summary
    if len(chunks) == 1:
        return summarize_chunk(chunks[0])

    # Multiple chunks → part summaries
    for i, chunk in enumerate(chunks):
        summaries.append(f"Part {i+1}:\n{summarize_chunk(chunk)}")

    merged_summaries = "\n\n".join(summaries)
    return merged_summaries


async def send_long_message(target, text):
    for i in range(0, len(text), 2000):
        await target.send(
            text[i:i+2000],
            allowed_mentions=discord.AllowedMentions.none()
        )


@commands.cooldown(1, 60, commands.BucketType.channel)
@bot.command()
async def tldr(
    ctx,
    hours: int = 6,
    source_channel: discord.TextChannel = None,
    output_channel: discord.TextChannel = None,
    bots: str = "no",
):
    source = source_channel or ctx.channel
    output = output_channel or ctx.channel

    if hours > 720:
        await output.send("Maximum allowed range is 720 hours.")
        return

    include_bots = bots.lower() in {"yes", "y", "true", "1"}
    messages = await get_messages(
        source,
        hours,
        command_message_id=ctx.message.id if source.id == ctx.channel.id else None,
        include_bots=include_bots
    )

    if not messages:
        await output.send("No messages found in that time window.")
        return

    await output.send("Summarizing conversation...", allowed_mentions=discord.AllowedMentions.none())
    summary = summarize_chunk(messages, compact=True)
    await send_long_message(output, summary)


@commands.cooldown(1, 60, commands.BucketType.channel)
@bot.command()
async def tldr_full(
    ctx,
    hours: int = 6,
    source_channel: discord.TextChannel = None,
    output_channel: discord.TextChannel = None,
    bots: str = "no",
):
    source = source_channel or ctx.channel
    output = output_channel or ctx.channel

    if hours > 720:
        await output.send("Maximum allowed range is 720 hours.")
        return

    include_bots = bots.lower() in {"yes", "y", "true", "1"}
    messages = await get_messages(
        source,
        hours,
        command_message_id=ctx.message.id if source.id == ctx.channel.id else None,
        include_bots=include_bots
    )

    if not messages:
        await output.send("No messages found in that time window.")
        return

    await output.send("Summarizing conversation in parts...", allowed_mentions=discord.AllowedMentions.none())
    summary = summarize_full(messages)
    await send_long_message(output, summary)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send("cooldown")
        return

    print("----- COMMAND ERROR -----")
    traceback.print_exception(type(error), error, error.__traceback__)
    print("-------------------------")

    await ctx.send("Command failed. Check logs.", allowed_mentions=discord.AllowedMentions.none())

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)

