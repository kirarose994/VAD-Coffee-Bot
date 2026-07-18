# Changelog

## Telegram history-recovery foundation

- Added an adapter-neutral, privacy-minimal normalized message contract that reuses the existing
  participation and POP classifiers without changing live Bot API processing.
- Added dormant schema-v14 history-recovery sources, fixed-boundary runs, derived inbox items,
  checkpoints, and an independent `telegram_mtproto_history_recovery` lease name.
- No Telethon dependency, Telegram connection, authentication, replay, or production activation
  is included in this foundation.

## Bot API singleton safety

- Added an additive schema-v13 SQLite lease that is acquired before Telegram polling.
- Added atomic startup exclusion, heartbeat renewal, expiry takeover, owner-checked release, and
  fail-closed shutdown when ownership cannot be verified.
- Added a sanitized startup identity line without tokens, secrets, or environment dumps.
- Disabled both executable historical launchers under `bot_backup_before_tracker/` while keeping
  the archive available as reference.
- Documented that separate Autoscale filesystems still require singleton hosting.
## POP late handling and historical reconciliation

- Added schema version 13 with a one-time late-alert claim and a separate append-only table for
  Owner-confirmed historical POP decisions; existing schema-v12 evidence remains unchanged.
- Calculate exact lateness from the original Telegram timestamp and configured Eastern cutoff.
  Valid late proof remains Late, retains the earliest canonical evidence, and never becomes Missing.
- Added one deduplicated informational late heads-up in the existing POP-review destination. It
  creates no warning, strike, or automatic consequence.
- Added an Owner-only dry-run reconciliation workflow with timestamp validation, optional source
  reference, repeated authorization, second confirmation over reliable evidence, and full audit.
- Approved Away Notice excusals remain authoritative when a creator voluntarily posts proof.

## POP reliability

- Recognize screenshots, captioned media, ordinary links, and Telegram story/channel/post links
  in the configured Sellers Chat POP topic without requiring the word “POP.”
- Re-evaluate edited messages while preserving immutable identity, location, Thursday, weekly,
  and active-creator checks.
- Added restart-safe 24-hour preservation and outage evidence in schema version 12.
- Preserve queued updates, use original Telegram timestamps for On Time/Late, retain earliest
  evidence, and route clear or ambiguous text safely to Admin review.
- Added durable update/evidence idempotency, runtime heartbeats, conservative recovery confidence,
  delayed post-catch-up scheduling, and an Owner-only POP Recovery Report.
- Route inconclusive Telegram preservation checks to Admin review without alleging early removal.
- Added explicit, audited Admin confirmation before recording early removal.
- Kept POP proof in Sellers Chat; no bot submission flow was added and no production migration was run.

## Version 1.0 UX polish

- Added a compact Owner-only Community Pulse with privacy-safe drill-downs.
- Grouped Owner Tools into daily operations, system, recovery, and setup screens.
- Reworded Participation Today around “Not counted” and “Still to Check In.”
- Added a private, preview-only weekly encouragement and a role-safe What’s New page.
- Kept production scheduling, core status rules, routing, and database schema unchanged.

- Added operation-specific Telegram polling incident grouping, quiet-window recovery, and thresholded Owner escalation in schema version 10.

## Multi-role permission upgrade

- Added additive Creator, Admin, and Owner memberships in schema version 9.
- Existing creator records and histories remain canonical by Telegram ID.
- Configured Admins receive Creator capabilities; Owners receive Admin and Creator capabilities.
- Added audited Owner/Admin assignment synchronization and additive home navigation.

## Unreleased

- Added Telegram privacy-mode visibility and live participation-location diagnostics.
- Made real accepted participation events verify ordinary-message access and Participation Monitor readiness.

- Group transient Telegram/httpx read failures into durable incidents with first seen, last seen,
  occurrence count, Open/Resolved status, sanitized tracebacks, bounded retry, and automatic recovery.
- Added additive SQLite schema version 8 for restart-safe system incident tracking.

- Added permission-aware Community Snapshots for Owners and Admins.
- Added an Owner-configurable, 9:00 AM Eastern Daily Admin Brief with durable once-per-day delivery.
- Added urgent-event routing and owner-visible, deduplicated delivery-failure handling.
- Kept Community Status separate from protected System Health diagnostics.
- Added additive SQLite schema version 7 for Daily Admin Brief delivery claims.

- Enforced distinct Owner, Admin, Creator, and Buyer interfaces.
- Added persistent audited Owner Setup for chat/topic routing and participation rules.
- Added bot-permission and configuration-problem reporting to chat/topic verification.
- Fixed owner/admin creator enrollment and archived-identity resolution.
- Made meaningful-message thresholds configurable.
- Confirmed active ordering handlers remain absent and historical code remains archive-only.
- Added the complete developer, role, operations, security, and recovery documentation set.
- Added primary role homes, Telegram Locations, Participation Monitor, and Participation Event Log.
- Centralized category-specific Admin topic routing with durable delivery failures.
- Added private creator support requests and Admin handling.
- Reinforced immutable Telegram-ID self-service isolation.
- Added additive SQLite schema version 5.
- Added Owner Setup & Readiness, Full System Check, safe Test Center, and resumable setup wizard.
- Added unassigned known bot users, People & Roles onboarding, and copyable role instructions.
- Added private deduplicated startup warnings and honest backup visibility.
- Added additive SQLite schema version 6 for role-neutral bot-user discovery.

## 1.1

Centralized POP deadlines, added guided workflows, friendly timelines/audit, Needs Attention,
Admin Queue, Away Notices, warning/strike memory, templates, and mobile navigation polish.
