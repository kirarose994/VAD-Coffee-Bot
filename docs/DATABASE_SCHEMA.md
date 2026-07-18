# Database Schema

SQLite schema version 13 is initialized and migrated by `database.initialize_database()`.

Version 13 adds the `process_leases` singleton table without rewriting existing incidents or
operational history. Version 12 introduced POP reliability and outage-recovery metadata; version
10 added operation-specific transport incident metadata.

| Table | Purpose |
|---|---|
| `creators` | Creator identity, approval, availability, participation anchor, soft deletion |
| `community_members` | General creator/buyer/community identity keyed by Telegram ID |
| `engagement_events` | Accepted and rejected participation decisions |
| `notifications` | Idempotent two-day and three-day delivery claims |
| `pop_submissions`, `pop_excuses` | Weekly proof, review state, and approved excusal |
| `absence_requests`, `availability_history` | Away Notice workflow and status history |
| `creator_warnings`, `member_warnings` | Warning/strike records |
| `audit_events`, `audit_history` | Append-oriented current and legacy accountability |
| `admin_notes`, `announcements` | Private notes and outbound communication |
| `message_templates`, `template_revisions` | Reusable messaging and edit history |
| `resources` | Configurable Help Center content |
| `system_state` | Health markers and audited operational configuration overrides |
| `process_leases` | Expiring ownership and heartbeat for the single Bot API poller |
| `support_requests`, `support_messages` | Private creator-bound support history |
| `delivery_failures` | Durable routing failures with safe references and retry state |
| `bot_users` | People who privately started the bot; this does not assign a role |
| `user_roles` | Additive Creator/Admin/Owner memberships and removal history |

Telegram ID is the creator/member primary key, so duplicate creator identities cannot exist.
Foreign keys, unique indexes, WAL mode, and a busy timeout protect consistency.

## Version 13 migration

Startup creates `process_leases` idempotently. Its primary key permits one row per lease name;
the active poller stores a unique instance ID, acquisition/heartbeat/expiry timestamps, and a
sanitized startup-source label. Acquisition uses an immediate SQLite write transaction so two
near-simultaneous processes cannot both win. Heartbeat and release operations require the current
instance ID, preventing an expired process from modifying a successor's lease.

Rollback to version 12 code is non-destructive: older code ignores `process_leases`. Because
version 12 has no singleton enforcement, rollback requires operators to verify manually that only
one polling process is active.

## Version 9 migration

Startup creates `user_roles`, seeds Creator membership from existing creator rows, and attaches
Admin/Owner memberships from the current audited configuration. Configured staff without a
creator row receive one active profile keyed by the same Telegram ID; an existing non-archived
staff profile is activated without replacing its history. Archived profiles are never restored
automatically. Re-running synchronization is idempotent.

Rollback to version 8 code is non-destructive: older code ignores `user_roles` and continues to
use the unchanged creator and configuration tables. Back up the database before deployment; do
not drop the additive table during rollback.
