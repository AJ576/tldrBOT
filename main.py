import discord
from discord.ext import commands
from groq import Groq
from datetime import datetime, timedelta
import os
from pathlib import Path
from dotenv import load_dotenv
import re
import traceback



load_dotenv(dotenv_path=Path(__file__).with_name(".env"))
TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")
if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY in .env")

client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL = "llama-3.3-70b-versatile"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="/",   # changed from "!"
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none(),
    help_command=None,    # so your custom /help works cleanly
)

async def get_messages(channel, hours=6, command_message_id=None, include_bots=False):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    messages = []

    async for msg in channel.history(limit=2000, after=cutoff):
        if (not include_bots) and msg.author.bot:
            continue
        if command_message_id and msg.id == command_message_id:
            continue

        # Use clean_content so mentions are readable (e.g., @dabi)
        content = (msg.clean_content or "").strip()
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


def enforce_tldr_shape(text: str, max_sections: int = 5) -> str:
    """
    Keep single TLDR readable:
    - max 5 sections
    - each section has a bold heading
    - short body under each heading
    """
    if not text:
        return text

    text = text.replace("\r\n", "\n").strip()
    sections = [s.strip() for s in re.split(r"\n\s*\n+", text) if s.strip()]

    cleaned_sections = []
    for section in sections[:max_sections]:
        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        if not lines:
            continue

        heading = lines[0]
        body = " ".join(lines[1:]).strip()

        # If the model forgot the bold heading, force one.
        if not re.match(r"^\*\*.*\*\*$", heading):
            heading = heading.strip(":")
            heading = f"**{heading}**"

        # Keep body short.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
        body = " ".join(sentences[:4]).strip()

        if body:
            cleaned_sections.append(f"{heading}\n{body}")
        else:
            cleaned_sections.append(heading)

    return "\n\n".join(cleaned_sections).strip()


def summarize_chunk(chunk, compact: bool = False):
    text = "\n".join(chunk)

    extra_rules = """
- Output ONLY 5 to 6 sections.
- Each section must start with a short bold heading in Markdown with an emoji, like: **🔥 Some Heading**
- After each heading, write 3 to 6 short sentences.
- Bold every person's name when mentioned, like **Aditya** or **dabi**.
- Leave one blank line between sections.
- No bullets.
- No intro line.
- No conclusion line.
"""

    prompt = f"""
You are summarizing a Discord chat.

Rules (strict):
- Be humorous/sarcastic.
- Keep attribution accurate.
{extra_rules}

Conversation:
{text}
"""
    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            top_p=0.9,
        )
        raw = completion.choices[0].message.content or ""
        cleaned = sanitize_summary(raw)
        if compact:
            return enforce_tldr_shape(cleaned, max_sections=5)
        return cleaned
    except Exception:
        return "[Groq API request failed]"


def summarize_full(messages):
    chunks = list(chunk_messages(messages))
    summaries = []

    # Single chunk → styled summary
    if len(chunks) == 1:
        return summarize_chunk(chunks[0], compact=True)

    # Multiple chunks → styled part summaries
    for i, chunk in enumerate(chunks):
        part_summary = summarize_chunk(chunk, compact=True)
        summaries.append(f"**🧩 Part {i+1}**\n{part_summary}")

    merged_summaries = "\n\n".join(summaries)
    return merged_summaries


async def send_long_message(target, text):
    for i in range(0, len(text), 2000):
        await target.send(
            text[i:i+2000],
            allowed_mentions=discord.AllowedMentions.none()
        )


@commands.cooldown(1, 30, commands.BucketType.channel)
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


@commands.cooldown(1, 30, commands.BucketType.channel)
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


@bot.command(name="tldr_help", aliases=["help_tldr"])
async def tldr_help(ctx):
    text = (
        "**Discord TLDR Bot — Help**\n\n"
        "`/tldr [hours] [source_channel] [output_channel] [bots]`\n"
        "- Compact summary (default 6 hours)\n"
        "- `bots`: include bot messages (default: no)\n\n"
        "**Examples**\n"
        "- `/tldr`\n"
        "- `/tldr 24`\n"
        "- `/tldr 6 #general`\n"
        "- `/tldr 6 #general #tldr-output yes`\n\n"
        "`/tldr_full [hours] [source_channel] [output_channel] [bots]`\n"
        "- Chunked multi-part summary\n"
        "- Example: `/tldr_full 12 #general #tldr-output no`\n\n"
        "`/tldr_help` or `/help_tldr` to show this message."
    )
    await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())


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

