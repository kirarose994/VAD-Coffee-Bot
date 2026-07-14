# VAD Operations Bot rollout guide

## Architecture

- `bot/main.py`: application startup and handler registration
- `bot/navigation.py`: role-aware Home/Back/Cancel menus and nonce validation
- `bot/operations.py`: absence, queue, note, announcement, role, export, restore, and health workflows
- `bot/tracker.py`: registration, engagement, inactivity, POP, and reports
- `bot/database.py`: backward-compatible SQLite schema and data operations
- `bot/permissions.py`: role and individual permission enforcement
- `bot/config.py`: environment configuration and editable resource defaults
- `bot_backup_before_tracker/`: non-executable Coffee Date archive

## Migration and backup

Before first production start:

1. Stop every competing Telegram polling process.
2. Copy `bot/vad_tracker.db`, including any `-wal` and `-shm` files after a clean stop,
   to a dated private backup outside the repository.
3. Record the current Git commit and current Replit Secret key names.
4. Start the new code once. `initialize_database()` adds columns and tables without
   dropping creator, engagement, notification, POP, or legacy audit data.
5. Run owner system-health and operational reports before enabling routine use.

New tables: `absence_requests`, `availability_history`, `admin_notes`, `audit_events`,
`announcements`, `resources`, `pop_excuses`, `creator_warnings`, and `message_templates`.
The current schema version is 3. Existing important records gain
soft-deletion and restoration metadata where applicable.

## Rollback

1. Stop the bot.
2. Preserve the post-migration database for investigation; do not erase it.
3. Restore the dated pre-migration database backup.
4. check out the recorded prior commit or redeploy the prior reviewed version.
5. Restore the prior environment configuration and start exactly one poller.

The added SQLite columns are harmless to older readers, but restoring the full backup
is the supported rollback because older code does not understand approved absences.

## Menu map

- Home
  - Creator: registration, availability, vacation, sick day, POP, activity, status, history, contact
  - Admin: registration/absence/POP queues, alerts, creators, search, reports, calendar, announcements
  - Owner: audit, deleted records, roles, histories, analytics, settings, export, restore, health
  - Reports
  - Calendar
  - Resources
  - Support

Every submenu has Home, Back, and Cancel. Expired/reused menu buttons return safely to Home.

## Permission matrix

| Capability | Creator | Admin | Owner |
|---|---:|---:|---:|
| Own registration/status/absence/POP | Yes | Operational view | Yes |
| Registration, absence, POP review | No | Assigned permission | Yes |
| Reports/search/calendar | Own only | Assigned permission | Yes |
| Notes/announcements | No | Assigned permission | Yes |
| Complete audit and actor identity | No | No | Yes |
| Deleted records and restore | No | No | Yes |
| Roles, sensitive permissions, export, health | No | No | Yes |
| Alter or erase audit events | No | No | No |

## Audit events

Implemented events include creator registration/status, availability, absence request and
review, automatic POP excusal, POP submission/review, engagement counted/ignored,
warning/alert creation, admin-note creation, announcements, settings, roles, permissions,
exports, soft deletion, and restoration. Events retain actor, action, target, previous/new
values, reason, related IDs, source location where available, result, and timestamp.
Warning creation, acknowledgment/removal, and template-message delivery are also audited
and appear in the creator timeline.

## Manual phone checklist

1. As an unregistered user, run `/start`; confirm Admin and Owner are hidden.
2. Register, then verify a second tap does not create duplicate official records.
3. As an approved creator, change Available/Unavailable and inspect My Status.
4. Submit vacation and sick-day requests; cancel once and confirm once.
5. Tap the same confirmation twice; verify the second tap fails safely.
6. As an admin with matching permission, open each queue and approve/deny/clarify.
7. Verify unauthorized creators cannot use review commands or manipulated callbacks.
8. Verify an approved absence appears in the calendar and pauses engagement expectations.
9. Verify a Thursday inside an approved absence reports POP as excused.
10. Submit POP in the wrong chat/topic/day or without a POP caption; verify it is ignored.
11. Submit valid POP once; verify a duplicate receives no second credit.
12. Send greetings, emojis, photos, filler, links, exact repeats, and punctuation-modified repeats; verify none count.
13. Test the two-day warning and three-day alert in a private test database/configuration.
14. Preview and cancel an announcement; then send to a small test audience.
15. Soft-delete a test creator; verify only an owner can list and restore it.
16. As both configured owners, confirm identical Owner menus and audit access.
17. As an admin, confirm `/admin_history`, export, restore, role, and health access are denied.
18. Restart the bot and verify no duplicate warnings, POP credit, reviews, or announcements.
19. Confirm `/start` contains no Coffee menu and no Coffee callbacks are accepted.
20. Confirm the Creator dashboard clearly shows participation, POP, standing, Away Notice,
    and availability.
21. Add one warning, two warnings, and three strikes in a test profile; verify the standing
    indicators and owner-review state.
22. Acknowledge a warning from its dashboard button and confirm the timeline updates.
23. Preview every message template, cancel one, deliver one, and verify the audit event.
24. Page backward and forward through a creator timeline as creator and authorized admin.

## Deployment

After review and merge only: configure secrets, back up the database, stop competing
pollers, start `cd bot && python main.py`, and monitor structured console logs. This
repository change does not deploy, restart the bot, or modify Replit Secrets.
