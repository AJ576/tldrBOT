import traceback
import discord
from discord.ext import commands
from config import Config
from utils.messages import get_messages
from utils.formatting import send_long_message
from services.summarizer import summarize_chunk, summarize_full, summarize_parallel


class TldrCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _fetch_and_summarize(self, ctx, hours, source_channel, output_channel, bots, mode="default"):
        source = source_channel or ctx.channel
        output = output_channel or ctx.channel

        if hours > Config.max_hours:
            await output.send(
                f"Max lookback is **{Config.max_hours} hours**. Try `/tldr {Config.max_hours}` or less."
            )
            return

        include_bots = bots.lower() in {"yes", "y", "true", "1"}
        messages = await get_messages(
            source,
            hours,
            command_message_id=ctx.message.id if source.id == ctx.channel.id else None,
            include_bots=include_bots,
        )

        if not messages:
            await output.send("No messages found in that time window.")
            return

        await output.send(
            "Summarizing conversation...",
            allowed_mentions=discord.AllowedMentions.none(),
        )

        if mode == "full":
            summary = summarize_full(messages)
        else:
            # Default: parallel fan-out → merge into one cohesive summary
            summary = await summarize_parallel(messages)

        await send_long_message(output, summary)

    @commands.cooldown(1, Config.cooldown_seconds, commands.BucketType.channel)
    @commands.command()
    async def tldr(self, ctx, hours: int = 6, source_channel: discord.TextChannel = None,
                   output_channel: discord.TextChannel = None, bots: str = "no"):
        await self._fetch_and_summarize(ctx, hours, source_channel, output_channel, bots)

    @commands.cooldown(1, Config.cooldown_seconds, commands.BucketType.channel)
    @commands.command()
    async def tldr_full(self, ctx, hours: int = 6, source_channel: discord.TextChannel = None,
                        output_channel: discord.TextChannel = None, bots: str = "no"):
        await self._fetch_and_summarize(ctx, hours, source_channel, output_channel, bots, mode="full")

    @commands.command(name="tldr_help", aliases=["help_tldr"])
    async def tldr_help(self, ctx):
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

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send("cooldown")
            return

        print("----- COMMAND ERROR -----")
        traceback.print_exception(type(error), error, error.__traceback__)
        print("-------------------------")
        await ctx.send("Command failed. Check logs.", allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(TldrCog(bot))
