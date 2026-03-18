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
            "- Example: `/tldr_full 12 #general #tldr-output false`\n"
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


async def setup(bot):
    await bot.add_cog(TldrCog(bot))
