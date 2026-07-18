# Owner Guide

## Community Snapshot and Daily Admin Brief

Open **Community Snapshot** near the top of Owner Home for live creator, participation, POP,
Away Notice, support, accountability, and operational-health totals. Tappable detail buttons open
the corresponding queue. Community Status describes current operations; **System Health** remains
the separate protected diagnostic area.

Open **Setup → System Settings → Daily Admin Brief** to enable the brief, choose 8:00, 9:00, or
10:00 AM Eastern, choose the destination, control weekends, zero-count rows, and System Health,
verify the destination, or send an isolated test. The default is disabled at 9:00 AM Eastern.

Owners Kira and Alex have equal access when both numeric IDs are securely configured. Use
Owner Home for Needs Attention, community operations, reports, audit, archives, restoration,
access, health, exports, Telegram Locations, and Participation Monitor.

Open Setup from the target Telegram group or topic. Verify Current Chat/Topic shows the
detected IDs, forum state, bot permissions, configuration matches, participation status, and
problems. Choose a destination, review the confirmation, then apply it. Changes are stored in
SQLite, audited, and restored after restart; Replit Secrets are not edited by the bot.

Participation Event Log shows concise counted and ignored outcomes without retaining full
message text. Support Requests stay in Needs Attention until handled or resolved.

Review three-strike cases and destructive actions manually. Never share exports publicly.

## POP reliability

POP recognition uses immutable Telegram ID plus the configured Sellers Chat and POP thread IDs;
it never depends on the visible topic name. Screenshots and qualifying links are recognized
without opening, fetching, or storing the submitted URL. Weekly uniqueness keeps the earliest
qualifying record.

The preservation monitor runs every 15 minutes and persists its state in SQLite so restarts do
not duplicate review items. Because Telegram does not reliably expose arbitrary message deletion
or historical-message lookup to ordinary bots, a due check becomes **Unable to verify — Admin
review required** instead of an accusation. Admins may confirm preservation or, after directly
verifying reliable evidence and confirming the protected action, record early removal. Each
uncertain or confirmed-removal alert is claimed once.

## POP outage recovery

Polling starts without dropping Telegram's pending updates and uses one `getUpdates` consumer.
A startup recovery run records the previous heartbeat, waits for pending messages to pass through
normal idempotent handlers, and only then permits reconciliation and ordinary scheduled checks.

Open **Owner Tools → Recovery → POP Recovery Report** for the latest outage window, recovered
update counts, current-week totals, manual-review references, and confidence. Owners also receive
one private restart summary. **Complete** means the recorded outage fits inside the conservative
recoverable window; **Partial** or **Unknown** means a gap may remain. Telegram does not provide
arbitrary full supergroup history, and the report never claims to have searched it.

For an already-ended Thursday, use this as a dry review list. Do not rewrite historical records
or mark strikes without explicit Owner review and reliable evidence.

Choose **Owner Tools → Recovery → POP Recovery Report → Reconcile Affected Week** for the
schema-v13 historical workflow. Choose a generated week and creator, select On Time, Late,
Excused, Needs Review, or Missing, and review the dry-run preview. On Time and Late require the
original visible Telegram date/time in Eastern Time; a source reference is optional. The bot
calculates lateness from that timestamp and the configured cutoff without storing a duplicate
duration. Confirming a change over reliable Telegram-observed evidence requires a second explicit
confirmation. Every saved decision is append-only and audited with the reason **Manual historical
reconciliation after pre-recovery outage**. The workflow never searches Telegram history, invents
message IDs, creates warnings or strikes, or rewrites the underlying Telegram evidence.

Every reconciliation step rechecks the environment-backed Owner role. Keep only the intended
Owners in `OWNER_USER_IDS`; never place real Telegram IDs in source code or documentation.

## Setup and readiness

Open **Setup & Readiness** to see one plain-language status for every required group, topic,
timer, route, database check, scheduler marker, backup marker, and delivery failure. Tap any
incomplete item to open the exact setup screen. **Run Full System Check** reads Telegram and
database state but sends no real creator notifications.

Use **Complete Initial Setup** for the resumable eight-step wizard. Use **Test Center** only
with the displayed safe test messages; they are intercepted before real participation is
written. The test page explains where to act, what should happen, and whether data changes.

## Adding people

Ask the person to open the bot privately and tap Start. They then appear under **People &
Roles → Pending Bot Users** without a role. Select them and explicitly choose Admin, Lead
Admin, creator invitation, or leave unassigned. Admin access never creates a creator profile,
creator approval never creates Admin access, and only secure numeric Owner IDs grant Owner.

For Alex, use **Copy Alex Owner Instructions**. Add her verified numeric ID to secure Owner
configuration, restart, and confirm Owner Home appears. Do not authorize Alex by name.

## Backups

The bot does not claim an external Replit backup exists. A missing or old backup remains
yellow. Stop the bot before privately copying the SQLite database and WAL/SHM files. Code in
GitHub plus the database are both required for recovery.
