# Admin Guide

## Community Snapshot

Community Snapshot shows only the sections allowed by your assigned permissions. POP, Away Notice,
participation, support, accountability, and System Health sections are independently hidden when
not assigned. Buttons and record lookups recheck permission on every use.

Admins see only assigned moderation and communication tools. Typical tools are Active
Creators, Creator Standing, private notes, reports, and Message Center. Review queues appear
only when an Owner grants their corresponding permission.

Admins cannot access owner history, configuration, exports, restoration, security health, or
role management. Every moderation and messaging action is audited.

Support Requests can be assigned, replied to, noted, escalated, or resolved when the Admin
has that permission. Replies are stored before delivery so a blocked private message is not lost.

## Thursday POP preservation

Creators post screenshots, images, and qualifying links only in the configured Sellers Chat POP
topic. The bot does not provide a proof-submission flow. One creator receives one weekly record,
even if additional proof is posted or an eligible message is edited.

Wednesday proof begins a durable 48-hour preservation check. Thursday and accepted Friday proof begin a durable 24-hour preservation check. Telegram's Bot API does not provide a
reliable general lookup or deletion update for arbitrary group messages. When the bot cannot
verify preservation, the POP queue says **Unable to verify — Admin review required**. This is
inconclusive: never treat it as confirmed early removal, a warning, or a strike. Record **Early
removal confirmed** only after directly verifying reliable evidence; the confirmation is audited
and alerted once.

The regular deadline is Thursday at 11:59 p.m. ET. Friday proof is accepted as Late only from
12:00 a.m. through 11:59 a.m. ET. At Friday noon, unresolved creators become Missing and the
durable Admin review workflow begins. Proof received at noon or later requires an authorized
manual reconciliation or excusal; the bot never issues a strike automatically.

POP review distinguishes **On Time**, **Late**, **Excused**, **Submitted — Needs Review**, and
**Missing**. Clear text proof is reviewable; greetings, emoji-only messages, vague statements,
and unrelated conversation do not qualify. Evidence is correlated only for the same creator in
the configured numeric chat/topic and a five-minute window. A covering approved Away Notice
remains Excused even when the creator voluntarily posts proof.

The first qualified late proof for a creator creates one informational heads-up in
the existing POP review location. It includes the original Eastern Time posting time, exact
calculated lateness, week, and retained source-message reference. Duplicate proof does not repeat
the alert. A late heads-up never creates a warning, strike, or automatic consequence. Historical
reconciliation is Owner-only; Regular Admins cannot create or change those decisions.

After restart, normal schedules wait for Telegram's pending-update catch-up window. Owners—not
ordinary Admins—receive the private recovery confidence report.
