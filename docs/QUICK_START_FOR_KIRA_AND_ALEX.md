# Quick Start for Kira and Alex

This is the shortest path from a deployed bot to a verified working VAD Operations Bot.

1. **Confirm both Owners.** Kira opens **Owner Home → People & Roles → Owners**. Alex opens
   the bot privately and taps **Start**. Add Alex's verified numeric ID to the secure Owner
   configuration (`OWNER_USER_IDS`, comma-separated), restart once, and confirm Alex sees
   **Owner Home**. Never authorize by name.
2. **Open Setup & Readiness.** Tap **✅ Setup & Readiness**. Yellow means setup is still
   needed, red means a problem was detected, and white means a safe test has not run yet.
3. **Verify the Main Group.** In the Main VAD supergroup, open **Telegram Locations → Verify
   Main Group**, check that the chat ID is `-1003543892255`, then confirm.
4. **Verify General.** Inside the actual General participation topic, use **Verify
   Participation Topic**. Do not guess a topic ID. Confirm only when the detected location is
   correct.
5. **Verify POP.** In the Sellers group, verify the Sellers Group and POP Topic. POP is
   separate from participation.
6. **Verify Admin destinations.** In each Admin forum topic, verify Registration, Away Notice,
   POP Review, Reports/Participation, Moderation, Support, and Health.
7. **Run safe tests.** Open **🧪 Test Center**. Follow the displayed location and expected
   result. Safe participation messages never change real creator totals.
8. **Run the final check.** Tap **🩺 Run Full System Check**. Follow every yellow, red, or
   white item until the result matches the real Telegram setup.
9. **Create a database backup.** Stop the bot before privately copying `vad_tracker.db` and
   its WAL/SHM companion files. GitHub contains code, not live creator history.

No setup page displays the Telegram bot token. Do not put database files, bot tokens, or
private exports in GitHub.
