# VAD Operations Bot

Telegram operations application for creator registration, availability, absences,
meaningful engagement, inactivity, Thursday POP, operational reporting, announcements,
and owner oversight.

The creator experience opens with a supportive explanation of the bot and Away Notices,
then presents a status card covering participation, weekly POP, standing, latest Away
Notice, and availability. Warning/strike records are documented community memory—not
automatic punishment—and creators can acknowledge warnings from their dashboard.

Mobile UX uses compact two-column action grids, concise status cards, permission-filtered
admin tools, consolidated owner navigation, supportive empty states, and consistent
Home/Back controls on passive pages, with Cancel reserved for active confirmations.
Creator-facing copy describes independent community
participation rather than employment or workplace management.

Version 1.1 adds owner **Needs Attention** and permission-filtered **Admin Queue** screens,
consistent status icons, time-to-reminder guidance, five privacy-friendly Away Notice
categories, expanded audited templates, general community-member identity support, and an
optional deduplicated daily owner summary.

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
- `DAILY_OWNER_SUMMARY_ENABLED` — defaults to `false`; no summary job is registered unless true
- `DAILY_OWNER_SUMMARY_TIME` — Eastern Time `HH:MM`, defaults to `09:00`

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

## Community memory and messaging

- `/warning_add TELEGRAM_ID warning|strike reason` records an audited warning or strike.
- Creators view and acknowledge active warnings from the Creator dashboard.
- `/warning_remove WARNING_ID reason` removes an item from standing calculations while
  preserving its timeline and audit history.
- Three active strikes display `Owner review required`; the bot does not automatically
  impose disciplinary action.
- Second warnings and three-strike cases appear in Needs Attention. Three strikes require a
  human owner decision and never remove anyone from Telegram automatically.
- `/template_list` lists reusable messages and `/template_preview` previews and confirms
  delivery. Default templates cover friendly, participation, POP, welcome, community
  check-in, warning, and strike messaging.
- `/template_update TEMPLATE_KEY new text` is owner-only and preserves both versions in
  template revisions and the audit trail.
- `/creator_timeline TELEGRAM_ID` provides authorized, paginated chronological history.

See [OPERATIONS_ROLLOUT.md](../docs/OPERATIONS_ROLLOUT.md) for migration, deployment,
rollback, menus, permissions, and manual testing.
