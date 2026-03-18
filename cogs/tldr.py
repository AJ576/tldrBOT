from datetime import datetime, timedelta, timezone
import traceback
import discord
from discord import app_commands
from discord.ext import commands
from config import Config
from utils.messages import get_messages
from utils.formatting import send_long_message
from services.summarizer import summarize_full, summarize_parallel


class TldrCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _reply(self, interaction: discord.Interaction, text: str, ephemeral: bool = True):
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(text, ephemeral=ephemeral)

    async def _fetch_and_summarize(self, interaction: discord.Interaction, hours, source_channel, output_channel, bots, mode="default"):
        source = source_channel or interaction.channel
        output = output_channel or interaction.channel

        if not isinstance(source, discord.TextChannel) or not isinstance(output, discord.TextChannel):
            await self._reply(interaction, "This command only supports text channels.", ephemeral=True)
            return

        if hours > Config.max_hours:
            await self._reply(
                interaction,
                f"Max lookback is **{Config.max_hours} hours**. Try `/tldr {Config.max_hours}` or less.",
                ephemeral=True,
            )
            return

        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)

        messages = await get_messages(
            source,
            hours,
            command_message_id=None,
            include_bots=bots,
        )

        if not messages:
            await self._reply(interaction, "No messages found in that time window.", ephemeral=True)
            return

        if mode == "full":
            summary = summarize_full(messages)
        else:
            summary = await summarize_parallel(messages)

        await send_long_message(output, summary)
        await self._reply(interaction, f"Done. Posted in {output.mention}.", ephemeral=True)

    async def _fetch_user_messages(self, channel, user_id: int, hours: int, include_bots: bool = False):
        """Fetch only messages from a specific user by ID."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        print(
            f"[collector] user start channel={getattr(channel, 'id', 'unknown')} "
            f"user_id={user_id} hours={hours} cutoff={cutoff.isoformat()}"
        )

        messages = []
        idx = 1

        async for msg in channel.history(
            limit=None,
            after=cutoff,
            oldest_first=True,
        ):
            if msg.author.id != user_id:
                continue

            content = (msg.clean_content or "").strip()
            if not content:
                continue

            messages.append(f"{idx}. {msg.author.display_name}: {content}")
            idx += 1

        print(
            f"[collector] user done channel={getattr(channel, 'id', 'unknown')} "
            f"user_id={user_id} messages_collected={len(messages)}"
        )
        return messages

    @app_commands.command(name="tldr", description="Compact summary (default 6 hours)")
    @app_commands.describe(
        hours="How many hours back to summarize (max 24)",
        source_channel="Channel to read messages from",
        output_channel="Channel to post summary in",
        bots="Include bot messages",
    )
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.channel_id))
    async def tldr(
        self,
        interaction: discord.Interaction,
        hours: app_commands.Range[int, 1, 24] = 6,
        source_channel: discord.TextChannel | None = None,
        output_channel: discord.TextChannel | None = None,
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
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.channel_id))
    async def tldr_full(
        self,
        interaction: discord.Interaction,
        hours: app_commands.Range[int, 1, 24] = 6,
        source_channel: discord.TextChannel | None = None,
        output_channel: discord.TextChannel | None = None,
        bots: bool = False,
    ):
        await self._fetch_and_summarize(interaction, hours, source_channel, output_channel, bots, mode="full")

    @app_commands.command(name="tldr_help", description="Show TLDR command help")
    async def tldr_help(self, interaction: discord.Interaction):
        text = (
            "**Discord TLDR Bot — Help**\n\n"
            "`/tldr [hours] [source_channel] [output_channel] [bots]`\n"
            "- Compact summary (default 6 hours)\n"
            "- `bots`: include bot messages (default: false)\n\n"
            "**Examples**\n"
            "- `/tldr`\n"
            "- `/tldr 24`\n"
            "- `/tldr 6 #general`\n"
            "- `/tldr 6 #general #tldr-output true`\n\n"
            "`/tldr_full [hours] [source_channel] [output_channel] [bots]`\n"
            "- Chunked multi-part summary\n"
            "- Example: `/tldr_full 12 #general #tldr-output false`\n\n"
            "`/tldr_user <username> [hours] [source_channel]`\n"
            "- Roast a user based on their messages (default 24 hours)\n"
            "- Example: `/tldr_user john 24`\n"
        )
        await self._reply(interaction, text, ephemeral=True)

    @tldr.error
    async def tldr_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await self._reply(interaction, "cooldown", ephemeral=True)
            return
        print("----- APP COMMAND ERROR (tldr) -----")
        traceback.print_exception(type(error), error, error.__traceback__)
        print("-------------------------------------")
        await self._reply(interaction, "Command failed. Check logs.", ephemeral=True)

    @tldr_full.error
    async def tldr_full_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await self._reply(interaction, "cooldown", ephemeral=True)
            return
        print("----- APP COMMAND ERROR (tldr_full) -----")
        traceback.print_exception(type(error), error, error.__traceback__)
        print("------------------------------------------")
        await self._reply(interaction, "Command failed. Check logs.", ephemeral=True)

    @app_commands.command(name="tldr_user", description="Roast a user based on their messages")
    @app_commands.describe(
        user="User to roast",
        hours="How many hours back (default 24)",
        source_channel="Channel to read from (default current)",
    )
    @app_commands.checks.cooldown(1, Config.cooldown_seconds, key=lambda i: (i.guild_id, i.channel_id))
    async def tldr_user(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        hours: app_commands.Range[int, 1, 24] = 24,
        source_channel: discord.TextChannel | None = None,
    ):
        source = source_channel or interaction.channel

        if not isinstance(source, discord.TextChannel):
            await self._reply(interaction, "This command only supports text channels.", ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)

        messages = await self._fetch_user_messages(source, user.id, hours, include_bots=False)

        if not messages:
            await self._reply(
                interaction,
                f"No messages from **{user.display_name}** in the last {hours} hour(s).",
                ephemeral=True,
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

        raw = _call_groq(prompt)
        if raw.startswith("[") and raw.endswith("]"):
            return f"Couldn't roast **{username}** right now. Try again later."
        return raw.strip() or f"**{username}** is too mysterious to roast."

    @tldr_user.error
    async def tldr_user_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await self._reply(interaction, "cooldown", ephemeral=True)
            return
        print("----- APP COMMAND ERROR (tldr_user) -----")
        traceback.print_exception(type(error), error, error.__traceback__)
        print("------------------------------------------")
        await self._reply(interaction, "Command failed. Check logs.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TldrCog(bot))
