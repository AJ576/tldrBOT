import discord
from collections import deque
from datetime import timedelta, timezone, datetime

from config import Config


async def _collect(channel, *, after=None, before=None, command_message_id=None,
                   include_bots=False, author_id=None, label="start"):
    """Walk channel history oldest->newest, keeping at most max_messages_fetched.

    When the window holds more than the cap, the OLDEST messages are dropped so
    the recap still covers the most recent activity. Returns (lines, truncated).
    """
    print(
        f"[collector] {label} channel={getattr(channel, 'id', 'unknown')} "
        f"after={after.isoformat() if after else None} "
        f"before={before.isoformat() if before else None} "
        f"include_bots={include_bots} author_id={author_id}"
    )

    cap = Config.max_messages_fetched
    kept = deque(maxlen=cap)
    seen = 0

    guild = getattr(channel, "guild", None)
    author_name_cache = {}

    async def _resolve_name(author):
        if not guild:
            return getattr(author, "display_name", str(author))
        if author.id in author_name_cache:
            return author_name_cache[author.id]

        member = guild.get_member(author.id)
        if member is None:
            try:
                member = await guild.fetch_member(author.id)
            except (discord.NotFound, discord.HTTPException):
                member = None

        name = member.display_name if member is not None else getattr(author, "display_name", str(author))
        author_name_cache[author.id] = name
        return name

    async for msg in channel.history(limit=None, after=after, before=before, oldest_first=True):
        if command_message_id and msg.id == command_message_id:
            continue
        if (not include_bots) and msg.author.bot:
            continue
        if author_id is not None and msg.author.id != author_id:
            continue

        content = (msg.clean_content or "").strip()
        if not content:
            continue

        seen += 1
        author_name = await _resolve_name(msg.author)
        kept.append(f"{author_name}: {content}")

    truncated = seen > cap
    messages = [f"{i}. {line}" for i, line in enumerate(kept, start=1)]

    print(
        f"[collector] {label} done channel={getattr(channel, 'id', 'unknown')} "
        f"matched={seen} kept={len(messages)} truncated={truncated}"
    )
    return messages, truncated


async def get_messages(channel, hours=6, command_message_id=None, include_bots=False):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return await _collect(
        channel,
        after=cutoff,
        command_message_id=command_message_id,
        include_bots=include_bots,
        label="window",
    )


async def get_messages_between(channel, start_dt, end_dt, command_message_id=None, include_bots=False):
    """Collect messages in [start_dt, end_dt), oldest->newest."""
    return await _collect(
        channel,
        after=start_dt,
        before=end_dt,
        command_message_id=command_message_id,
        include_bots=include_bots,
        label="day",
    )


async def get_user_messages(channel, user_id, hours=24, include_bots=False):
    """Collect only messages authored by user_id."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return await _collect(
        channel,
        after=cutoff,
        include_bots=include_bots,
        author_id=user_id,
        label="user",
    )


def chunk_messages(messages, chunk_size=200):
    for i in range(0, len(messages), chunk_size):
        yield messages[i:i + chunk_size]
