# Configuration

## Required bootstrap values

- `TELEGRAM_BOT_TOKEN`: Telegram token, stored only in Replit Secrets.
- `OWNER_USER_IDS`: comma-separated numeric IDs for Kira and Alex.
- `MAIN_CHAT_ID`: Main VAD supergroup; currently `-1003543892255`.

## Optional bootstrap values

`LEAD_ADMIN_USER_IDS`, `ADMIN_USER_IDS`, `ADMIN_PERMISSIONS_JSON`, `GIRLS_CHAT_ID`,
`POP_CHAT_ID`, `POP_THREAD_ID`, `ADMIN_CHAT_ID`, `REPORTS_THREAD_ID`, routing topic IDs,
`BUYER_GROUP_ID`, `TIMEZONE`, inactivity thresholds, POP deadline settings, and meaningful
message thresholds.

`PARTICIPATION_TOPIC_IDS` accepts comma-separated topic IDs. When `MAIN_CHAT_ID` is set and
this list is empty, only non-topic General messages match; forum General must be detected and
added if Telegram supplies a thread ID. Environment values bootstrap the database; audited
Owner Setup overrides then take precedence after startup.
