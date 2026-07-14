# VAD Operations Bot

The VAD Operations Bot is a role-aware Telegram application for creator registration,
meaningful participation, Thursday POP, Away Notices, reminders, warnings, communication,
and owner oversight.

Participation is tracked only for approved creators in owner-configured Main Group topics.
POP is a separate Sellers Group/topic workflow and never counts as participation. Roles are
additive: Admins also have Creator capabilities, and Owners have Creator, Admin, and Owner
capabilities. Buyers remain separate.

Replit starts the bot with:

```text
cd bot && python main.py
```

Start with the [documentation index](docs/README.md) for architecture, setup, roles,
configuration, deployment, backup, security, troubleshooting, and contributor guidance.

Historical Coffee Date code is retained only in `bot_backup_before_tracker/`; it is not part
of the active application.
