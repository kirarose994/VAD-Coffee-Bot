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
| `/topicid` | Returns the current Telegram topic ID |
| `/creator_register` | Submit creator registration for approval |
| `/vacation YYYY-MM-DD` | Pause tracking through an Eastern Time date |

Role-based access uses immutable Telegram IDs from Replit Secrets:

- `owner`: all operational permissions plus exclusive access to audit records,
  history changes, deletion/configuration history, and administrator identities.
- `lead_admin` and `admin`: operational management including creator approvals,
  rejections, deactivation and deletion, vacations, POP decisions, reports, and
  day-to-day configuration. Neither role can view `/admin_history`, reset audit
  history, or see which administrator performed an action.

Creator self-service registration and vacation commands remain available to the creator.
Every mutation is written to the audit history with actor, target, action, details, and time.

Temporary setup commands are enabled only while `SETUP_MODE=true`: `/myid` returns the
requester's numeric user ID; `/chatid` and `/threadid` return the current group/topic IDs
only after Telegram confirms the requester is an administrator of that group. Disable setup
mode after collecting the IDs. These commands never display secrets or environment values.

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
| `LEAD_ADMIN_USER_IDS` | _(none)_ | Comma-separated Telegram IDs allowed operational administrative actions |
| `ADMIN_USER_IDS` | _(none)_ | Comma-separated Telegram IDs allowed operational administration |
| `OWNER_USER_IDS` | _(none)_ | Comma-separated Telegram IDs with owner-only audit and history access |
| `GIRLS_CHAT_ID` | _(none)_ | Group where registered-creator engagement is tracked |
| `GIRLS_THREAD_ID` | _(none)_ | Optional topic containing ordinary engagement |
| `POP_THREAD_ID` | _(none)_ | Thursday POP-proof topic |
| `REPORTS_THREAD_ID` | _(none)_ | Optional admin report topic |
| `TIMEZONE` | `America/New_York` | Display and scheduling timezone |
| `INACTIVITY_WARNING_HOURS` | `48` | Warning threshold |
| `INACTIVITY_ALERT_HOURS` | `72` | Admin-alert threshold |
| `SETUP_MODE` | `false` | Temporarily enables numeric Telegram ID discovery commands |

Credentials and chat configuration belong in Replit Secrets/environment variables.
The SQLite tracker stores UTC instants and uses Eastern Time for Thursday and vacation rules.

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
