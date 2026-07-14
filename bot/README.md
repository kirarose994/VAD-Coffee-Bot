# VAD Operations Bot

Telegram operations application for creator registration, availability, absences,
meaningful engagement, inactivity, Thursday POP, operational reporting, announcements,
and owner oversight.

The active application starts with `cd bot && python main.py`. Coffee Date ordering is
not imported or registered. Its historical implementation remains only in
`bot_backup_before_tracker/`.

## Roles

- Creator: self-service registration, availability, absence requests, POP, personal
  status/history, and admin contact.
- Admin and lead admin: operational actions filtered by `ADMIN_PERMISSIONS_JSON`.
- Owner: every operational action plus complete audit, deleted records, restoration,
  roles/permissions, exports, settings history, and system health.

Owners are identified only by immutable numeric Telegram IDs. Both supported owner
variables are combined; use `OWNER_USER_IDS` for continuity. Never store IDs in code.

## Environment variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `OWNER_USER_IDS` — comma-separated numeric owner IDs

Operational:

- `ADMIN_USER_IDS`
- `LEAD_ADMIN_USER_IDS`
- `ADMIN_PERMISSIONS_JSON` — optional JSON object mapping Telegram IDs to permission lists
- `ADMIN_CHAT_ID`
- `GIRLS_CHAT_ID`
- `GIRLS_THREAD_ID`
- `POP_THREAD_ID`
- `REPORTS_THREAD_ID`
- `TIMEZONE` — defaults to `America/New_York`
- `INACTIVITY_WARNING_HOURS` — defaults to `48`
- `INACTIVITY_ALERT_HOURS` — defaults to `72`
- `SETUP_MODE` — temporary ID-discovery mode; normally `false`
- `LOG_LEVEL` — defaults to `INFO`

`OWNER_TELEGRAM_IDS` is accepted as an alias for owner IDs. Do not configure real IDs
in repository files.

## Admin permissions

Available permissions include `review_registrations`, `review_vacations`,
`review_sick_days`, `review_pop`, `view_creator_reports`, `manage_creators`,
`add_admin_notes`, `send_announcements`, and `adjust_warnings`. Owners always have all
permissions. Missing per-admin configuration defaults authorized admins to the normal
operational permission set.

## Safety

- Callback actions use per-user nonces and are single-use.
- Every callback and command rechecks server-side authorization.
- Audit events are append-only; `/history_reset` refuses deletion.
- Creator removal is soft deletion; owner restoration preserves history.
- Existing creator, engagement, notification, and POP data are migrated in place.
- SQLite uses foreign keys, WAL mode, busy timeouts, indexes, and uniqueness constraints.
- Secrets and runtime databases are ignored by Git.

See [OPERATIONS_ROLLOUT.md](../docs/OPERATIONS_ROLLOUT.md) for migration, deployment,
rollback, menus, permissions, and manual testing.
