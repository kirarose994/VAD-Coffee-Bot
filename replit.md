# VAD Coffee Lounge Bot

A Telegram ordering bot for VAD Coffee Lounge. Guides users through a 6-step inline-keyboard ordering flow, calculates an itemised receipt, and forwards orders to an admin group.

## Run & Operate

- **VAD Coffee Date Bot** workflow — runs `cd bot && python main.py`
- Required secret: `TELEGRAM_BOT_TOKEN`
- Optional secret: `ADMIN_CHAT_ID` (group chat ID for order forwarding)

## Stack

- Python 3.13
- python-telegram-bot v21 (async polling, ConversationHandler)

## Where things live

```
bot/
├── main.py           # Entry point + /groupid command
├── config.py         # Config class + all menu data + conversation states
├── order.py          # Full 6-step ConversationHandler (keyboards, handlers)
├── receipt.py        # Price calculation + receipt formatting
├── requirements.txt  # python-telegram-bot[job-queue]==21.10
└── handlers/
    └── error.py      # Global error handler
```

## Ordering flow

1. /start → Welcome + barista multi-select (≥ 2 required)
2. Size — Tall / Grande / Venti
3. Roast — Light / Medium / Dark
4. Flavor shots — multi-select with Skip (Cinnamon is the only paid shot)
5. Bakery — multi-select with Skip
6. Caffeine shot — Yes / No
7. Receipt with Submit / Cancel

Prices marked "each" are multiplied by the number of selected baristas.

## Connecting the admin group

1. Add the bot to your admin group
2. Send `/groupid` inside that group — bot replies with the chat ID
3. Add `ADMIN_CHAT_ID` as a Replit Secret
4. Restart the workflow

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Profiles/orders are in-memory; they reset on restart.
- `ADMIN_CHAT_ID` must be an integer (negative for groups). A malformed value logs a warning and disables forwarding rather than crashing.
- Package manager is `uv` (Replit-managed). Add packages via the package-management skill, not raw `pip install`.
