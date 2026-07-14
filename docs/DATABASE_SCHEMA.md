# Database Schema

SQLite schema version 4 is initialized and migrated by `database.initialize_database()`.

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

Telegram ID is the creator/member primary key, so duplicate creator identities cannot exist.
Foreign keys, unique indexes, WAL mode, and a busy timeout protect consistency.
