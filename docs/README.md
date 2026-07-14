# VAD Operations Bot Documentation

This directory is the maintained operating and developer manual for the VAD Operations Bot.
Start with [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md), then use
[OWNER_GUIDE.md](OWNER_GUIDE.md) or the guide for your role. Developers should read
[ARCHITECTURE.md](ARCHITECTURE.md), [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md), and
[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) before changing code.

The active product manages creator registration, participation, Thursday POP, Away Notices,
warnings, messaging, and owner oversight. The historical ordering application is isolated in
`bot_backup_before_tracker/` and is not imported, registered, scheduled, or displayed.

Documentation changes are required whenever behavior, configuration, permissions, data,
routing, deployment, or recovery procedures change.

Operational references include [PARTICIPATION_ENGINE.md](PARTICIPATION_ENGINE.md),
[POP_ENGINE.md](POP_ENGINE.md), and [SUPPORT_REQUEST_WORKFLOW.md](SUPPORT_REQUEST_WORKFLOW.md).
