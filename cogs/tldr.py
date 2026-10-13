import asyncio
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Union
import discord
from discord import app_commands
from discord.ext import commands
from config import Config
from utils.messages import get_messages, get_messages_between, get_user_messages
from utils.formatting import send_long_message
from services.summarizer import summarize_full, summarize_parallel

SupportedChannel = Union[
    discord.TextChannel,
    discord.Thread,
    discord.VoiceChannel,
    discord.StageChannel,
]


class TldrCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _reply(self, interaction: discord.Interaction, text: str, ephemeral: bool = True):
        try:
            if len(text) > 2000:
                text = text[:1997] + "..."
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(text, ephemeral=ephemeral)
        except discord.HTTPException as exc:
            # Interaction token expired / already acknowledged elsewhere: nothing to do.
            print(f"[bot] could not reply to interaction: {exc}")

    async def _defer(self, interaction: discord.Interaction, ephemeral: bool = True) -> bool:
        """Acknowledge the interaction immediately. Returns False if the token is already dead.

        Discord gives us 3 seconds to acknowledge, so this must be the first thing
        a command does -- before permission math, history fetches or LLM calls.
        """
        if interaction.response.is_done():
            return True

        # How much of the 3s budget was already gone before we got here. A large
        # value means the gateway delivered it late; a small one means we were slow.
        age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        started = time.monotonic()

        try:
            await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        except discord.HTTPException as exc:
            print(
                f"[bot] could not defer interaction: {exc} "
                f"(age_on_arrival={age:.2f}s defer_call={time.monotonic() - started:.2f}s "
                f"gateway_latency={self.bot.latency * 1000:.0f}ms)"
            )
            return False

        elapsed = time.monotonic() - started
        if age + elapsed > 1.0:
            print(
                f"[bot] slow ack: age_on_arrival={age:.2f}s defer_call={elapsed:.2f}s "
                f"gateway_latency={self.bot.latency * 1000:.0f}ms"
            )
        return True

    async def _resolve_channels(
        self,
        interaction: discord.Interaction,
        source_channel: SupportedChannel | None = None,
        output_channel: SupportedChannel | None = None,
        check_output: bool = True,
    ):
        """Validate the requested channels and the caller's access to them.

        Returns (source, output) or None if the command should stop. Without this,
        any member could have the bot read a channel they cannot see and repost it
        somewhere they can.
        """
        source = source_channel or interaction.channel
        output = output_channel or interaction.channel

        if source is None:
            await self._reply(interaction, "Could not determine the source channel.")
            return None

        # Fetch channel if it is a partial channel or missing permission attributes
        if not hasattr(source, "permissions_for") and hasattr(source, "id"):
            try:
                source = self.bot.get_channel(source.id) or await self.bot.fetch_channel(source.id)
            except Exception:
                pass

        if check_output and output is not None and not hasattr(output, "permissions_for") and hasattr(output, "id"):
            try:
                output = self.bot.get_channel(output.id) or await self.bot.fetch_channel(output.id)
            except Exception:
                pass

        valid_types = (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)
        if not isinstance(source, valid_types):
            await self._reply(interaction, "This command only supports text channels, threads, and voice chats.")
            return None

        if check_output and not isinstance(output, valid_types):
            await self._reply(interaction, "This command only supports text channels, threads, and voice chats.")
            return None

        guild = getattr(source, "guild", None) or interaction.guild
        if not guild:
            await self._reply(interaction, "This command only works inside a server.")
            return None

        member = interaction.user
        if not isinstance(member, discord.Member):
            try:
                member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)
            except Exception:
                pass

        if not isinstance(member, discord.Member):
            await self._reply(interaction, "This command only works inside a server.")
            return None

        caller_source = source.permissions_for(member)
        if not (caller_source.view_channel and caller_source.read_message_history):
            await self._reply(interaction, f"You don't have access to read {source.mention}.")
            return None

        if check_output and output:
            caller_output = output.permissions_for(member)
            if not caller_output.send_messages:
                await self._reply(interaction, f"You don't have permission to post in {output.mention}.")
                return None

        me = guild.me
        if me is None and self.bot.user:
            try:
                me = guild.get_member(self.bot.user.id) or await guild.fetch_member(self.bot.user.id)
            except Exception:
                me = None

        if me is not None:
            bot_source = source.permissions_for(me)
            if not (bot_source.view_channel and bot_source.read_message_history):
                await self._reply(interaction, f"I can't read {source.mention}.")
                return None

            if check_output and output:
                bot_output = output.permissions_for(me)
                if not bot_output.send_messages:
                    await self._reply(interaction, f"I can't post in {output.mention}.")
                    return None

        return source, output

    def _truncation_note(self, truncated: bool) -> str:
        if not truncated:
            return ""
        return (
            f"\n(Only the most recent {Config.max_messages_fetched} messages were "
            f"summarized — the window had more than that.)"
        )

    async def _fetch_and_summarize(self, interaction: discord.Interaction, hours, source_channel, output_channel, bots, mode="default"):
        if not await self._defer(interaction):
            return

        resolved = await self._resolve_channels(interaction, source_channel, output_channel)
        if resolved is None:
            return
        source, output = resolved

        if hours > Config.max_hours:
            await self._reply(
                interaction,
                f"Max lookback is **{Config.max_hours} hours**. Try `/tldr {Config.max_hours}` or less.",
            )
            return

        messages, truncated = await get_messages(
            source,
            hours,
            command_message_id=None,
            include_bots=bots,
        )

        if not messages:
            await self._reply(interaction, "No messages found in that time window.")
            return

        if mode == "full":
            summary = await asyncio.to_thread(summarize_full, messages)
        else:
            summary = await summarize_parallel(messages)

        await send_long_message(output, summary)
        await self._reply(
            interaction,
            f"Done. Posted in {output.mention}.{self._truncation_note(truncated)}",
        )

    async def _fetch_and_summarize_day(
        self,
        interaction: discord.Interaction,
        date_str: str,
        source_channel,
        output_channel,
        bots: bool,
    ):
        if not await self._defer(interaction):
            return

        resolved = await self._resolve_channels(interaction, source_channel, output_channel)
        if resolved is None:
            return
        source, output = resolved

        try:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            await self._reply(interaction, "Invalid date. Use `YYYY-MM-DD` (UTC).")
            return

        day_end = day_start + timedelta(days=1)

        messages, truncated = await get_messages_between(
            source,
            day_start,
            day_end,
            command_message_id=None,
            include_bots=bots,
        )

        if not messages:
            await self._reply(interaction, f"No messages found on **{date_str}** (UTC).")
            return

        # Slightly more detailed than /tldr: use full mode for day recaps
        summary = await asyncio.to_thread(summarize_full, messages)

        await send_long_message(output, summary)
        await self._reply(
            interaction,
            f"Done. Posted day summary for **{date_str}** in {output.mention}."
            f"{self._truncation_note(truncated)}",
        )

    @app_commands.command(name="tldr", description="Compact summary (default 6 hours)")
    @app_commands.describe(
        hours="How many hours back to summarize (max 24)",
        source_channel="Channel to read messages from",
        output_channel="Channel to post summary in",
        bots="Include bot messages",
    )
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.user.id))
    async def tldr(
        self,
        interaction: discord.Interaction,
        hours: app_commands.Range[int, 1, 24] = 6,
        source_channel: SupportedChannel | None = None,
        output_channel: SupportedChannel | None = None,
        bots: bool = False,
    ):
        await self._fetch_and_summarize(interaction, hours, source_channel, output_channel, bots)

    @app_commands.command(name="tldr_full", description="Chunked multi-part summary")
    @app_commands.describe(
        hours="How many hours back to summarize (max 24)",
        source_channel="Channel to read messages from",
        output_channel="Channel to post summary in",
        bots="Include bot messages",
    )
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.user.id))
    async def tldr_full(
        self,
        interaction: discord.Interaction,
        hours: app_commands.Range[int, 1, 24] = 6,
        source_channel: SupportedChannel | None = None,
        output_channel: SupportedChannel | None = None,
        bots: bool = False,
    ):
        await self._fetch_and_summarize(interaction, hours, source_channel, output_channel, bots, mode="full")

    @app_commands.command(name="tldr_day", description="Summarize one full day (YYYY-MM-DD, UTC)")
    @app_commands.describe(
        date="Date in YYYY-MM-DD (UTC)",
        source_channel="Channel to read messages from",
        output_channel="Channel to post summary in",
        bots="Include bot messages",
    )
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.user.id))
    async def tldr_day(
        self,
        interaction: discord.Interaction,
        date: str,
        source_channel: SupportedChannel | None = None,
        output_channel: SupportedChannel | None = None,
        bots: bool = False,
    ):
        await self._fetch_and_summarize_day(interaction, date, source_channel, output_channel, bots)

    @app_commands.command(name="tldr_user", description="Roast a user based on their messages")
    @app_commands.describe(
        user="User to roast",
        hours="How many hours back (default 24)",
        source_channel="Channel to read from (default current)",
    )
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.user.id))
    async def tldr_user(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        hours: app_commands.Range[int, 1, 24] = 24,
        source_channel: SupportedChannel | None = None,
    ):
        if not await self._defer(interaction, ephemeral=False):
            return

        resolved = await self._resolve_channels(interaction, source_channel, None, check_output=False)
        if resolved is None:
            return
        source, _ = resolved

        messages, _truncated = await get_user_messages(source, user.id, hours, include_bots=False)

        if not messages:
            await self._reply(
                interaction,
                f"No messages from **{user.display_name}** in the last {hours} hour(s).",
            )
            return

        print(f"[ai] tldr_user roast start user={user.display_name} ({user.id}) message_count={len(messages)}")
        roast = await self._generate_user_roast(user.display_name, messages)
        print(f"[ai] tldr_user roast done chars={len(roast or '')}")

        await self._reply(interaction, roast, ephemeral=False)

    async def _generate_user_roast(self, username: str, messages: list[str]) -> str:
        """Generate a roast based ONLY on user's actual messages."""
        from services.summarizer import _call_groq

        prompt = f"""\
You are a Discord server member writing a funny roast about **{username}** based on their recent messages.

RULES (STRICT):
- ONLY use facts directly from their messages below.
- NEVER invent hobbies, relationships, locations, or behaviors.
- NEVER reference events that aren't in their messages.
- Make it playful and funny, NOT mean or offensive.
- Keep it 2-4 sentences max.
- Bold the username: **{username}**

Their recent messages:
{chr(10).join(messages)}

Write the roast now:"""

        raw = await asyncio.to_thread(_call_groq, prompt)
        if raw.startswith("[") and raw.endswith("]"):
            return f"Couldn't roast **{username}** right now. Try again later."
        return raw.strip() or f"**{username}** is too mysterious to roast."

    @app_commands.command(name="tldr_help", description="Show TLDR command help")
    async def tldr_help(self, interaction: discord.Interaction):
        text = (
            "**Discord TLDR Bot — Help**\n\n"
            "`/tldr [hours] [source_channel] [output_channel] [bots]`\n"
            "- Compact summary (default 6 hours, max 24)\n"
            "- `bots`: include bot messages (default: false)\n\n"
            "**Examples**\n"
            "- `/tldr`\n"
            "- `/tldr 24`\n"
            "- `/tldr 6 #general`\n"
            "- `/tldr 6 #general #tldr-output true`\n\n"
            "`/tldr_full [hours] [source_channel] [output_channel] [bots]`\n"
            "- Chunked multi-part summary\n"
            "- Example: `/tldr_full 12 #general #tldr-output false`\n\n"
            "`/tldr_day <YYYY-MM-DD> [source_channel] [output_channel] [bots]`\n"
            "- Summarize one full day (UTC)\n"
            "- Example: `/tldr_day 2026-09-24 #general`\n\n"
            "`/tldr_user <user> [hours] [source_channel]`\n"
            "- Roast a user based on their messages (default 24 hours)\n"
            "- Example: `/tldr_user @john 24`\n\n"
            f"Cooldown: {Config.cooldown_seconds}s per user, per server."
        )
        await self._reply(interaction, text)

    async def _handle_error(self, name: str, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await self._reply(interaction, f"Slow down — try again in {error.retry_after:.0f}s.")
            return
        print(f"----- APP COMMAND ERROR ({name}) -----")
        traceback.print_exception(type(error), error, error.__traceback__)
        print("-------------------------------------")
        await self._reply(interaction, "Command failed. Check logs.")

    @tldr.error
    async def tldr_error(self, interaction, error):
        await self._handle_error("tldr", interaction, error)

    @tldr_full.error
    async def tldr_full_error(self, interaction, error):
        await self._handle_error("tldr_full", interaction, error)

    @tldr_day.error
    async def tldr_day_error(self, interaction, error):
        await self._handle_error("tldr_day", interaction, error)

    @tldr_user.error
    async def tldr_user_error(self, interaction, error):
        await self._handle_error("tldr_user", interaction, error)


async def setup(bot):
    await bot.add_cog(TldrCog(bot))
