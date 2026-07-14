# Setup Guide

For the shortest Owner workflow, begin with [QUICK_START_FOR_KIRA_AND_ALEX.md](QUICK_START_FOR_KIRA_AND_ALEX.md).

## Guided setup

1. Open **Owner Home → Complete Initial Setup**.
2. Confirm Owners. Alex must first open the bot privately and tap Start.
3. Verify Main Group ID `-1003543892255` from inside that group.
4. Verify the real General participation topic. Never guess its thread ID.
5. Verify the Sellers group and POP topic.
6. Verify each Admin destination from inside its forum topic.
7. Review reminder thresholds, Thursday cutoff, and `America/New_York`.
8. Run the labeled registration routing test and final Full System Check.

Progress is stored per Owner and resumes after restart. A location change always shows a
preview and confirmation before it is persisted and audited.

## Common incomplete statuses

- **Participation topic:** open Telegram Locations inside General and verify it.
- **Bot cannot read messages:** confirm the bot is in the Main group and privacy mode and
  permissions allow ordinary group messages to reach it.
- **Route not verified:** open the matching Admin topic and use its verification button.
- **Backup unknown:** stop the bot and create a private database backup; do not upload it to GitHub.
- **Delivery failure:** open Health, verify the destination, then rerun the safe route test.

The Full System Check never sends real creator reminders. Startup setup warnings are private
to configured Owners and deduplicated for each distinct missing-configuration state.

1. Configure the bot token and numeric Owner IDs securely.
2. Set the known Main Group bootstrap value to `-1003543892255`.
3. Start the bot and open Owner Dashboard → Setup from the Main Group General topic.
4. Choose Verify Current Topic. Do not guess its `message_thread_id`.
5. Confirm chat name, ID, forum status, topic ID, bot permissions, and detected problems.
6. Add the detected topic as a Participation Topic.
7. Repeat verification in the Sellers POP topic and set Seller Group, POP Group, and POP Topic.
8. Verify Admin and Buyer groups, then review reminder, timezone, and meaningful-message rules.

Owner changes are persisted in SQLite and audited. They do not rewrite Replit Secrets.
