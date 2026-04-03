from datetime import timedelta, timezone, datetime


async def get_messages(channel, hours=6, command_message_id=None, include_bots=False):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    print(
        f"[collector] start channel={getattr(channel, 'id', 'unknown')} "
        f"hours={hours} include_bots={include_bots} cutoff={cutoff.isoformat()}"
    )

    messages = []
    idx = 1

    async for msg in channel.history(
        limit=None,
        after=cutoff,
        oldest_first=True,
    ):
        if command_message_id and msg.id == command_message_id:
            continue
        if (not include_bots) and msg.author.bot:
            continue

        content = (msg.clean_content or "").strip()
        if not content:
            continue

        messages.append(f"{idx}. {msg.author.display_name}: {content}")
        idx += 1

    print(
        f"[collector] done channel={getattr(channel, 'id', 'unknown')} "
        f"messages_collected={len(messages)}"
    )
    return messages


async def get_messages_between(channel, start_dt, end_dt, command_message_id=None, include_bots=False):
    """Collect messages in [start_dt, end_dt), oldest->newest."""
    print(
        f"[collector] day start channel={getattr(channel, 'id', 'unknown')} "
        f"start={start_dt.isoformat()} end={end_dt.isoformat()} include_bots={include_bots}"
    )

    messages = []
    idx = 1

    async for msg in channel.history(
        limit=None,
        after=start_dt,
        before=end_dt,
        oldest_first=True,
    ):
        if command_message_id and msg.id == command_message_id:
            continue
        if (not include_bots) and msg.author.bot:
            continue

        content = (msg.clean_content or "").strip()
        if not content:
            continue

        messages.append(f"{idx}. {msg.author.display_name}: {content}")
        idx += 1

    print(
        f"[collector] day done channel={getattr(channel, 'id', 'unknown')} "
        f"messages_collected={len(messages)}"
    )
    return messages


def chunk_messages(messages, chunk_size=200):
    for i in range(0, len(messages), chunk_size):
        yield messages[i:i + chunk_size]
