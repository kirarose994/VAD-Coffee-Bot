# Architecture

## Runtime

`bot/main.py` loads environment configuration, initializes SQLite, overlays audited
owner-managed settings, registers handlers, and starts one Telegram long-polling process.
`.replit` runs `cd bot && python main.py`; the repository-root `main.py` is a convenience
wrapper.

## Modules

- `config.py` parses bootstrap environment settings.
- `runtime_config.py` persists and restores owner-approved operational overrides.
- `navigation.py` builds role-aware screens and nonce-protected callbacks.
- `permissions.py` resolves Owner, Lead Admin, Admin, and unprivileged access.
- `database.py` owns schema migration and durable operations.
- `tracker.py` routes registration, participation, POP, reminders, and reports.
- `engagement.py` classifies meaningful messages deterministically.
- `pop_policy.py` is the only POP deadline/status calculator.
- `operations.py` implements guided operational forms and queues.
- `presentation.py` formats human-readable Eastern Time timelines and audit entries.

Active code has no dependency on `bot_backup_before_tracker/`.
