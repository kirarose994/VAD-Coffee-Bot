# POP Engine

Community Snapshot, queues, reports, notifications, and the Daily Admin Brief all use the same
Eastern Time POP policy. “Missing” is impossible before the configured Thursday cutoff. An
immediate Admin exception is generated only after that deadline and is deduplicated by creator
and POP period.

POP accepts proof only from approved creators in the configured POP Group and POP Topic.
Submission credit is unique per creator and weekly period. Proof enters Pending/Awaiting
Review and records submission and review actors.

`pop_policy.py` is the only deadline calculator. Before the due date: Not Due Yet. On the due
date before cutoff: Due Today/Still Needed. After the Eastern cutoff: Missing. Submitted,
Awaiting Review, and Excused override deadline labels. Approved Away Notices may create a POP
excuse. POP processing is separate from participation and never grants engagement credit.
