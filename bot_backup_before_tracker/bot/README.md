# VAD Coffee Lounge Bot

A Telegram ordering bot for VAD Coffee Lounge. Guides users through a 6-step ordering flow with inline keyboards, calculates a price receipt, and forwards orders to an admin group.

## Flow

1. **/start** — Welcome message + barista selection (choose ≥ 2)
2. **Size** — Tall / Grande / Venti (price × baristas)
3. **Roast** — Light / Medium / Dark (price × baristas)
4. **Flavor Shots** — Vanilla, Caramel, Hazelnut (free) · Cinnamon (+$15 × baristas) · Skip
5. **Bakery** — Croissant / Cake Pop / Breakfast Sandwich (price × baristas) · Skip
6. **Caffeine Shot** — Yes (+$30 × baristas) / No
7. **Receipt** — Full itemised total with Submit / Cancel

## Commands

| Command    | Description |
|------------|-------------|
| `/start`   | Start or restart an order |
| `/cancel`  | Cancel the current order at any step |
| `/groupid` | (Use inside a group) Returns the group's chat ID |

## Project structure

```
bot/
├── main.py           # Entry point
├── config.py         # Config class + all menu data
├── order.py          # Full ConversationHandler (all steps & keyboards)
├── receipt.py        # Price calculation + receipt formatting
├── requirements.txt  # Python dependencies
└── handlers/
    └── error.py      # Global error handler
```

## Setup

### 1. Create a bot with @BotFather

Send `/newbot` to @BotFather and copy the token you receive.

### 2. Add required secret

Add `TELEGRAM_BOT_TOKEN` as a Replit Secret.

### 3. Connect an admin group (optional)

1. Add the bot to your admin group.
2. Send `/groupid` in that group — the bot replies with the chat ID.
3. Add `ADMIN_CHAT_ID` as a Replit Secret with that value.
4. Restart the **VAD Coffee Lounge Bot** workflow.

### 4. Optional environment variables

| Variable       | Default | Description |
|----------------|---------|-------------|
| `ADMIN_CHAT_ID`| _(none)_| Group chat ID for order forwarding |
| `LOG_LEVEL`    | `INFO`  | Logging level |

## Pricing logic

All prices marked **"each"** are multiplied by the number of selected baristas.

| Item | Price |
|------|-------|
| Tall | $30 × baristas |
| Grande | $60 × baristas |
| Venti | $120 × baristas |
| Light Roast | $10 × baristas |
| Medium Roast | $20 × baristas |
| Dark Roast | $40 × baristas |
| Cinnamon shot | $15 × baristas |
| Croissant | $75 × baristas |
| Cake Pop | $150 × baristas |
| Breakfast Sandwich | $200 × baristas |
| Caffeine shot | $30 × baristas |
