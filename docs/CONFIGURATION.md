# Configuration

## Daily Admin Brief

The in-bot Owner settings control enablement, Eastern delivery time, destination chat/topic,
weekend delivery, System Health inclusion, and whether zero-count rows appear. Runtime values are
persisted and audited. The normal default is disabled at `09:00` America/New_York. No Secret change
is required for routine in-bot adjustments.

## Required bootstrap values

- `TELEGRAM_BOT_TOKEN`: Telegram token, stored only in Replit Secrets.
- `OWNER_USER_IDS`: comma-separated numeric IDs for Kira and Alex.
- `MAIN_CHAT_ID`: Main VAD supergroup; currently `-1003543892255`.

## Optional bootstrap values

`ADMIN_USER_IDS`, `ADMIN_PERMISSIONS_JSON`, `GIRLS_CHAT_ID`,
`POP_CHAT_ID`, `POP_THREAD_ID`, `ADMIN_CHAT_ID`, `REPORTS_THREAD_ID`, routing topic IDs,
`BUYER_GROUP_ID`, `TIMEZONE`, inactivity thresholds, POP deadline settings, and meaningful
message thresholds.

`PARTICIPATION_TOPIC_IDS` accepts comma-separated topic IDs. When `MAIN_CHAT_ID` is set and
this list is empty, only non-topic General messages match; forum General must be detected and
added if Telegram supplies a thread ID. Environment values bootstrap the database; audited
Owner Setup overrides then take precedence after startup.

For the current Main VAD layout, General arrives with no thread ID. Owners should verify it and
choose **Use General for Participation**, which persists an explicit empty allow-list. Do not put
the Admin reports topic ID in `PARTICIPATION_TOPIC_IDS` or `PARTICIPATION_THREAD_IDS`.

Routing topic bootstrap keys are `REGISTRATION_THREAD_ID`, `AWAY_THREAD_ID`,
`POP_REVIEW_THREAD_ID`, `REPORTS_THREAD_ID`, `MODERATION_THREAD_ID`, `SUPPORT_THREAD_ID`,
`OWNER_REVIEW_THREAD_ID`, and `HEALTH_THREAD_ID`. Owners can later verify and persist these
non-secret destinations through Telegram Locations without changing code.
