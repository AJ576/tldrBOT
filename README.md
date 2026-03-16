# Discord TLDR Bot

A Discord bot that summarizes channel conversations with a humorous tone using Gemini.

## Features

- `!tldr` for a compact summary (default: last 6 hours)
- `!tldr_full` for chunked/longer summaries
- Optional source/output channels
- Optional bot-message inclusion
- Mention-safe output (`@everyone`/role/user pings disabled)

## Commands

### `!tldr`
Compact summary.

**Signature**
`!tldr [hours] [source_channel] [output_channel] [bots]`

- `hours` (optional, int): how far back to read (default: `6`)
- `source_channel` (optional, channel mention): where to read messages from
- `output_channel` (optional, channel mention): where to post summary
- `bots` (optional, `yes`/`no`): include bot messages (`no` by default)

**Examples**
- `!tldr`  
  Read current channel (last 6h), post in current channel, exclude bot messages.
- `!tldr 24`  
  Same channel, last 24h.
- `!tldr 6 #general`  
  Read from `#general`, post in current channel.
- `!tldr 6 #general #tldr-output`  
  Read from `#general`, post in `#tldr-output`.
- `!tldr 6 #general #tldr-output yes`  
  Same as above, but include bot messages.
- `!tldr 6 #general #tldr-output no`  
  Explicitly exclude bot messages.

---

### `!tldr_full`
Longer, chunked summary.

**Signature**
`!tldr_full [hours] [source_channel] [output_channel] [bots]`

**Examples**
- `!tldr_full`
- `!tldr_full 12`
- `!tldr_full 12 #general`
- `!tldr_full 12 #general #tldr-output`
- `!tldr_full 12 #general #tldr-output yes`

> Note: If you provide channels, keep argument order exactly as shown:
> `hours -> source_channel -> output_channel -> bots`

## Setup

1. Clone the repo
2. Create and activate a virtual environment
3. Install dependencies
4. Create `.env` from `.env.example`
5. Run the bot

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Environment Variables

This project currently reads these variables in [`main.py`](main.py):

- `DISCORD_TOKEN`
- `GEMINI_KEY`

See [`.env.example`](.env.example).

## Invite the Bot

https://discord.com/oauth2/authorize?client_id=1482553762559299728&permissions=68608&integration_type=0&scope=bot+applications.commands

## Notes for Open Source

- Never commit `.env`
- Use GitHub Secrets for CI/CD (if using Actions)
- Rotate leaked keys immediately

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
