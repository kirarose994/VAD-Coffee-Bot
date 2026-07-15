# Database Schema

SQLite schema version 10 is initialized and migrated by `database.initialize_database()`.

Version 10 adds operation-specific transport incident metadata (`operation`, `escalated_at`, and
`resolution_reason`) without rewriting existing incidents or operational history.

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
| `support_requests`, `support_messages` | Private creator-bound support history |
| `delivery_failures` | Durable routing failures with safe references and retry state |
| `bot_users` | People who privately started the bot; this does not assign a role |
| `user_roles` | Additive Creator/Admin/Owner memberships and removal history |

Telegram ID is the creator/member primary key, so duplicate creator identities cannot exist.
Foreign keys, unique indexes, WAL mode, and a busy timeout protect consistency.

## Version 9 migration

Startup creates `user_roles`, seeds Creator membership from existing creator rows, and attaches
Admin/Owner memberships from the current audited configuration. Configured staff without a
creator row receive one active profile keyed by the same Telegram ID; an existing non-archived
staff profile is activated without replacing its history. Archived profiles are never restored
automatically. Re-running synchronization is idempotent.

Rollback to version 8 code is non-destructive: older code ignores `user_roles` and continues to
use the unchanged creator and configuration tables. Back up the database before deployment; do
not drop the additive table during rollback.
