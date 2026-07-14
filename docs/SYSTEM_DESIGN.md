# System Design

Telegram updates flow through command handlers, protected callbacks, and finally generic
non-command message observers. Every privileged command and callback rechecks the numeric
Telegram user ID server-side.

Identity, role, and creator approval are independent. An Owner or Admin may also have a
creator profile, but administrative status alone never makes their messages count. A creator
must exist, be unarchived, and have status `active`.

Scheduled work uses database uniqueness claims so restarts cannot duplicate reminders.
Sensitive actions append audit events. Important removals are soft deletions, enabling
owner-only review and restoration.
