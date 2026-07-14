# Reminder Engine

The scheduler measures approved creators from their last meaningful participation or approval
anchor. After two full days, it sends a friendly private reminder. After three full days, when
there is no approved Away Notice, it sends an Admin follow-up alert. These reminders support
the community participation purpose; they are not a requirement to make an empty check-in.
Approved Away Notices pause elapsed expectations and provide a fair grace point after return.

At the configured warning threshold, the bot creates a supportive reminder claim. At the
configured alert threshold, it creates an admin follow-up claim. `(creator, cycle, kind)` is
unique, making jobs restart-safe and idempotent. Routing failures are audited and surfaced in
Needs Attention.
