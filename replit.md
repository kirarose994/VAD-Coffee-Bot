# VAD Coffee Date Bot

A Telegram bot that connects people for casual coffee chats and networking, built with python-telegram-bot v21.

## Run & Operate

- **VAD Coffee Date Bot** workflow — runs `cd bot && python main.py`
- After setting `TELEGRAM_BOT_TOKEN` as a Replit Secret, start the workflow to bring the bot online.

## Stack

- Python 3.13
- python-telegram-bot v21 (async, with APScheduler job-queue)
- python-dotenv

## Where things live

```
bot/
├── main.py              # Entry point — builds Application and starts polling
├── config.py            # Config (env vars), conversation states, keyboard constants
├── requirements.txt     # Python dependencies
├── handlers/
│   ├── start.py         # /start and /help
│   ├── register.py      # /register — 4-step ConversationHandler
│   ├── profile.py       # /profile
│   ├── match.py         # /match — overlap-score matching
│   └── error.py         # Global error handler
└── utils/
    ├── keyboards.py     # Reply / inline keyboard builders
    └── formatting.py   # Message text formatters
```

## Architecture decisions

- Profiles stored in `bot_data` (in-memory). Persist with a DB for production use.
- `ConversationHandler` added before plain command handlers to correctly intercept mid-conversation messages.
- Match scoring: `(shared availability slots × 2) + shared interests` — availability weighted higher.
- All handlers are `async` functions; errors are caught globally by `error_handler`.

## Product

Users can register a coffee date profile (name, availability slots, location, interests) through a guided multi-step conversation, then use `/match` to find a compatible partner based on shared availability and interests.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Profiles reset on restart (in-memory only). Add a DB for persistence.
- `TELEGRAM_BOT_TOKEN` must be set as a Replit Secret before starting the workflow.
- Package manager is `uv` (managed by Replit). Add packages via the package-management skill, not raw `pip install`.

## Pointers

- Bot token: add as Replit Secret `TELEGRAM_BOT_TOKEN`
- Optional secrets: `ADMIN_IDS` (comma-separated user IDs), `LOG_LEVEL`, `DEBUG`
