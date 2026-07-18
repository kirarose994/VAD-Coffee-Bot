# Database Schema

SQLite schema version 14 is initialized and migrated by `database.initialize_database()`.

Version 14 adds dormant Telegram history-recovery metadata without writing recovered operational
evidence. Version 13 added the `process_leases` singleton table, POP late-alert claim, and manual
reconciliation records without rewriting existing incidents or operational history. Version 12
introduced POP reliability and outage-recovery metadata; version 10 added operation-specific
transport incident metadata.

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
| `history_recovery_sources` | Disabled-by-default source mappings and durable scan checkpoints |
| `history_recovery_runs` | Fixed-boundary discovery/replay run state and confidence counters |
| `history_recovery_items` | Privacy-minimal derived message envelopes; no raw text, URLs, or media |
| `support_requests`, `support_messages` | Private creator-bound support history |
| `delivery_failures` | Durable routing failures with safe references and retry state |
| `bot_users` | People who privately started the bot; this does not assign a role |
| `user_roles` | Additive Creator/Admin/Owner memberships and removal history |

Telegram ID is the creator/member primary key, so duplicate creator identities cannot exist.
Foreign keys, unique indexes, WAL mode, and a busy timeout protect consistency.

## Version 14 migration

The version 14 foundation is additive and dormant. It creates independently checkpointed recovery
sources, fixed-boundary runs, and a derived-message inbox. Source location, one-active-run, and
source-peer/message uniqueness constraints make future discovery restart-safe. Inbox rows can
store identifiers, timestamps, minimal media indicators, hashes, and classifier outcomes, but
have no raw text, caption, URL, or media-content columns.

The reserved `telegram_mtproto_history_recovery` lease name uses the existing generic lease table
without interacting with `telegram_bot_api_poller`. No runtime acquires the new lease yet. Rolling
back to version 13 code is non-destructive because older code ignores these unused tables.

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
