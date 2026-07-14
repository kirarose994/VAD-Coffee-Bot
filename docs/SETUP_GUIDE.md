# Setup Guide

1. Configure the bot token and numeric Owner IDs securely.
2. Set the known Main Group bootstrap value to `-1003543892255`.
3. Start the bot and open Owner Dashboard → Setup from the Main Group General topic.
4. Choose Verify Current Topic. Do not guess its `message_thread_id`.
5. Confirm chat name, ID, forum status, topic ID, bot permissions, and detected problems.
6. Add the detected topic as a Participation Topic.
7. Repeat verification in the Sellers POP topic and set Seller Group, POP Group, and POP Topic.
8. Verify Admin and Buyer groups, then review reminder, timezone, and meaningful-message rules.

Owner changes are persisted in SQLite and audited. They do not rewrite Replit Secrets.
