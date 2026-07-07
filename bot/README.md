# VAD Coffee Date Bot

A Telegram bot that helps people connect for casual coffee chats and networking.

## Features

- **/register** — Multi-step conversation to create your coffee date profile  
  (name → availability → location → interests → confirmation)
- **/profile** — View your saved profile
- **/match** — Get matched with another user based on shared availability and interests
- **/help** — Show all available commands

## Project Structure

```
bot/
├── main.py                  # Entry point — builds and starts the bot
├── config.py                # Configuration (env vars, conversation states, constants)
├── requirements.txt         # Python dependencies
├── handlers/
│   ├── start.py             # /start and /help handlers
│   ├── register.py          # /register ConversationHandler (4-step flow)
│   ├── profile.py           # /profile handler
│   ├── match.py             # /match handler (overlap-score matching)
│   └── error.py             # Global error handler
└── utils/
    ├── keyboards.py          # Reply and inline keyboard builders
    └── formatting.py         # Message text formatters
```

## Setup

### 1. Create a bot with @BotFather

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the token you receive

### 2. Set the bot token

Add `TELEGRAM_BOT_TOKEN` as a Replit Secret (the padlock icon in the sidebar),  
or set it in a `.env` file locally:

```
TELEGRAM_BOT_TOKEN=your_token_here
```

### 3. Optional environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_IDS` | _(empty)_ | Comma-separated Telegram user IDs with admin access |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `DEBUG` | `false` | Enable debug mode |

### 4. Run the bot

```bash
cd bot
pip install -r requirements.txt
python main.py
```

## How matching works

Each profile stores a list of availability slots and interests. When `/match` is called,  
the bot scores every other registered user by:

```
score = (shared availability slots × 2) + shared interests
```

The highest-scoring candidate is shown as the match. If multiple candidates tie, one is chosen at random.

> **Note:** Profiles are stored in-memory and reset when the bot restarts. For persistence across restarts, integrate a database (e.g. PostgreSQL with psycopg2, or SQLite).
