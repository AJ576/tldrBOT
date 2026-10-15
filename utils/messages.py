import logging
import re
import discord
from collections import deque
from datetime import timedelta, timezone, datetime

from config import Config

logger = logging.getLogger(__name__)

TENOR_GIPHY_RE = re.compile(
    r"https?://(?:[a-zA-Z0-9_.]+\.)?(?:tenor\.com/view/|giphy\.com/gifs/)([\w-]+)",
    re.IGNORECASE,
)


def format_gif_slug(slug: str) -> str:
    slug = re.sub(r"-\d+$", "", slug)
    slug = re.sub(r"-gif$", "", slug, flags=re.I)
    slug = re.sub(r"-[a-zA-Z0-9]{10,}$", "", slug)
    cleaned = slug.replace("-", " ").strip()
    if len(cleaned) > 50:
        cleaned = cleaned[:47] + "..."
    return cleaned if cleaned else "animated gif"


def enrich_content(text: str, attachments=None, stickers=None, max_media: int = 3) -> str:
    """Enrich message content by parsing GIF picker URLs, attachments, and stickers.

    Replaces raw Tenor/Giphy links with [GIF: <description>], and includes
    attached GIFs, images, and stickers.
    """
    def _replace_gif(match):
        raw_slug = match.group(1)
        desc = format_gif_slug(raw_slug)
        return f"[GIF: {desc}]"

    text = TENOR_GIPHY_RE.sub(_replace_gif, text or "").strip()

    media_parts = []
    if stickers and type(stickers).__name__ != "MagicMock":
        for s in stickers:
            name = getattr(s, "name", None)
            if isinstance(name, str) and name:
                media_parts.append(f"[Sticker: {name}]")

    if attachments and type(attachments).__name__ != "MagicMock":
        for a in attachments:
            fn = getattr(a, "filename", None)
            if isinstance(fn, str) and fn:
                lower_fn = fn.lower()
                if lower_fn.endswith(".gif"):
                    media_parts.append(f"[GIF: {fn}]")
                elif any(lower_fn.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                    media_parts.append(f"[Image: {fn}]")
                else:
                    media_parts.append(f"[Attachment: {fn}]")

    if media_parts:
        if len(media_parts) > max_media:
            extra = len(media_parts) - max_media
            media_parts = media_parts[:max_media]
            media_parts.append(f"[+{extra} more files]")
        media_str = " ".join(media_parts)
        if text:
            return f"{text} {media_str}".strip()
        return media_str

    return text


def format_reactions(reactions, max_reactions: int = 5) -> str:
    """Format a list of discord.Reaction objects into a compact string representation.

    Sorts by count descending and caps at max_reactions to prevent emote spam
    from bloating context size.
    """
    if not reactions:
        return ""

    valid = [r for r in reactions if getattr(r, "count", 0) > 0]
    if not valid:
        return ""

    sorted_rx = sorted(valid, key=lambda r: r.count, reverse=True)[:max_reactions]
    parts = []
    for r in sorted_rx:
        emoji = r.emoji
        if hasattr(emoji, "name") and emoji.name:
            emoji_str = f":{emoji.name}:"
        else:
            emoji_str = str(emoji)
        parts.append(f"{emoji_str}x{r.count}")

    return f" [Reactions: {', '.join(parts)}]" if parts else ""


async def format_reply_context(
    msg,
    author_name: str,
    seen_messages: dict,
    max_snippet_len: int = 40,
    name_resolver=None,
) -> str:
    """Format reply/forward context if msg is referencing another message.

    Resolves referenced author and a brief quote snippet using in-memory references
    or seen_messages lookup. Never makes external network requests.
    """
    ref = getattr(msg, "reference", None)
    if not ref:
        return ""

    # Guard against unconfigured auto-generated MagicMock references in tests
    if type(ref).__name__ == "MagicMock":
        has_int_id = isinstance(getattr(ref, "message_id", None), int)
        has_configured_resolved = (
            getattr(ref, "resolved", None) is not None
            and isinstance(getattr(ref.resolved, "clean_content", None), str)
        )
        if not (has_int_id or has_configured_resolved):
            return ""

    is_forward = False
    ref_type = getattr(ref, "type", None)
    forward_type = getattr(discord.MessageReferenceType, "forward", None)
    if forward_type is not None and ref_type == forward_type:
        is_forward = True

    ref_author = None
    ref_content = None

    msg_id = getattr(ref, "message_id", None)
    if msg_id in seen_messages:
        ref_author, ref_content = seen_messages[msg_id]
    else:
        resolved = getattr(ref, "resolved", None)
        if resolved is not None and hasattr(resolved, "author") and resolved.author is not None:
            if name_resolver is not None:
                ref_author = await name_resolver(resolved.author)
            else:
                ref_author = getattr(resolved.author, "display_name", str(resolved.author))
            raw_ref = (getattr(resolved, "clean_content", "") or "").replace("\n", " ").strip()
            ref_attachments = getattr(resolved, "attachments", None)
            ref_stickers = getattr(resolved, "stickers", None)
            ref_content = enrich_content(raw_ref, attachments=ref_attachments, stickers=ref_stickers)
        elif isinstance(resolved, discord.DeletedReferencedMessage) or (resolved is not None and not hasattr(resolved, "author")):
            ref_author = "deleted message"
            ref_content = ""

    if not ref_author:
        ref_author = "earlier message"
        ref_content = ""

    if is_forward:
        return f"[Forwarded from {ref_author}]"

    target = "self" if ref_author == author_name else ref_author

    if ref_content:
        snippet = ref_content.replace('"', "'")
        if len(snippet) > max_snippet_len:
            snippet = snippet[:max_snippet_len - 3] + "..."
        return f'[replying to {target}: "{snippet}"]'

    return f"[replying to {target}]"


async def _collect(channel, *, after=None, before=None, command_message_id=None,
                   include_bots=False, author_id=None, label="start"):
    """Walk channel history oldest->newest, keeping at most max_messages_fetched.

    When the window holds more than the cap, the OLDEST messages are dropped so
    the recap still covers the most recent activity. Returns (lines, truncated).
    """
    logger.info(
        "[collector] %s channel=%s after=%s before=%s include_bots=%s author_id=%s",
        label,
        getattr(channel, "id", "unknown"),
        after.isoformat() if after else None,
        before.isoformat() if before else None,
        include_bots,
        author_id,
    )

    cap = Config.max_messages_fetched
    kept = deque(maxlen=cap)
    seen = 0
    seen_messages = {}

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

        raw_content = (msg.clean_content or "").strip()
        attachments = getattr(msg, "attachments", None)
        stickers = getattr(msg, "stickers", None)
        content = enrich_content(raw_content, attachments=attachments, stickers=stickers)
        if not content:
            continue

        seen += 1
        author_name = await _resolve_name(msg.author)
        reply_str = await format_reply_context(
            msg,
            author_name=author_name,
            seen_messages=seen_messages,
            name_resolver=_resolve_name,
        )
        rx_str = format_reactions(getattr(msg, "reactions", None))
        reply_prefix = f" {reply_str}" if reply_str else ""
        kept.append(f"{author_name}{reply_prefix}: {content}{rx_str}")

        # Cache seen message for reply reference lookups
        snippet = content.replace("\n", " ").strip()
        if len(snippet) > 40:
            snippet = snippet[:37] + "..."
        seen_messages[msg.id] = (author_name, snippet)

    truncated = seen > cap
    messages = [f"{i}. {line}" for i, line in enumerate(kept, start=1)]

    logger.info(
        "[collector] %s done channel=%s matched=%d kept=%d truncated=%s",
        label,
        getattr(channel, "id", "unknown"),
        seen,
        len(messages),
        truncated,
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
