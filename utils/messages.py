from datetime import datetime, timedelta


async def get_messages(channel, hours=6, command_message_id=None, include_bots=False):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    messages = []
    idx = 1

    async for msg in channel.history(
        limit=None,
        after=cutoff,
        oldest_first=True,  # important: timeline order
    ):
        if (not include_bots) and msg.author.bot:
            continue
        if command_message_id and msg.id == command_message_id:
            continue

        content = (msg.clean_content or "").strip()
        if not content:
            continue

        messages.append(f"[{idx}] {msg.author.display_name}: {content}")
        idx += 1

    return messages


def chunk_messages(messages, chunk_size=200):
    for i in range(0, len(messages), chunk_size):
        yield messages[i:i + chunk_size]
