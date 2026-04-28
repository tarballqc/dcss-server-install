# Discord bot (optional)

Posts wins, deaths, milestones, and a daily activity summary into a channel of your choice. Off by default.

## What you'll need

1. A bot application: https://discord.com/developers/applications → New Application → Bot tab
2. Copy the **bot token** (you'll need it once; it's secret)
3. Enable required intents in the Bot tab:
   - **Server Members Intent** — for role syncing
   - **Message Content Intent** — for slash command responses
4. Invite the bot to your guild with these scopes:
   - `bot` and `applications.commands`
   - Permissions: `Send Messages`, `Embed Links`, `Manage Roles`
5. Right-click the announcements channel → Copy ID (Discord developer mode required)
6. Right-click the guild → Copy ID

## Enabling

Either re-run `./install.sh` (it asks), or add to `.env`:

```env
DISCORD_BOT_TOKEN=your.bot.token.here
DISCORD_GUILD_ID=123456789012345678
DISCORD_CHANNEL_ID=987654321098765432
DISCORD_INVITE=abcDef         # optional, shown in the password-reset email footer
```

Then bring up the bot:

```bash
docker compose --profile discord up -d
```

It runs alongside the game container and shares `/data` for state.

## What it posts

| Event | Channel post |
|---|---|
| Win | `🏆 PlayerName won as DDFi (Trog) — XL27 D:1 in 12345 turns` + morgue link |
| Death (anything ≥ XL15 or with a notable cause) | `💀 PlayerName the Mighty (XL18 OgFi) was slain by an orc warrior on D:8` + morgue link |
| Milestone (rune found, branch entered, etc.) | terse `PlayerName found a silver rune of Zot.` |
| Daily summary | `Today: 14 games · 3 wins · most-played: SpEn` |

## Slash commands

The bot registers a few `/` commands per server:

- `/link` — links a player's DCSS username to their Discord account (used for role sync)
- `/scores` — top-10 leaderboard for the current month
- `/recent` — last 5 wins/deaths

## Troubleshooting

- **Bot online but silent**: check `docker compose logs discord-bot`. Most often a wrong channel/guild ID, or missing intents.
- **Commands don't show up**: Discord caches command lists for ~1 hour after registration. Try re-inviting the bot or wait.
- **"Missing permissions" on role sync**: the bot needs the **Manage Roles** permission, and its top role must be *above* any role it's trying to assign.

## Disabling

```bash
docker compose --profile discord stop discord-bot
docker compose rm -f discord-bot
```

Or just remove `DISCORD_BOT_TOKEN` from `.env` and the bot won't connect on next start.
