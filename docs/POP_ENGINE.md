# POP Engine

Community Snapshot, queues, reports, notifications, and the Daily Admin Brief all use the same
fixed America/New_York POP policy. Wednesday proof is accepted early with a 48-hour retention
requirement. Thursday proof is On Time through 11:59 p.m. ET with a 24-hour retention
requirement. Friday proof is Late only from 12:00 a.m. through 11:59 a.m. ET and also requires
24 hours of retention. At Friday noon, an unresolved creator becomes Missing and enters Admin
review; no strike is automatic.

POP accepts proof only from approved creators in the configured POP Group and POP Topic.
Submission credit is unique per creator and weekly period. Proof enters Pending/Awaiting
Review and records submission and review actors.

`pop_policy.py` is the only deadline calculator. Before Wednesday: Not Due Yet. Wednesday is the
early window, Thursday is Due Today, Friday morning is Still Needed, and Friday noon begins
Missing. Proof received at noon Friday or later is not credited automatically and requires an
authorized reconciliation or excusal. Submitted, Awaiting Review, and Excused override deadline
labels. Approved Away Notices may create a POP excuse. POP processing is separate from
participation and never grants engagement credit.
