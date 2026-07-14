# Owner Guide

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
