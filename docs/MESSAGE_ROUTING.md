# Message Routing

| Event | Destination |
|---|---|
| Meaningful participation | Configured Main Group plus approved participation topic |
| POP proof | Configured Sellers/POP Group plus POP Topic |
| New creator review | Admin Group registration topic, then reports fallback |
| Away Request | Admin Group Away topic, then reports fallback |
| Participation alerts/reports | Admin Group reports topic |
| Warnings/strikes | Moderation topic, then reports fallback |
| Creator support | Support topic, then reports fallback |
| Three-strike review | Owner Review topic and Owners |
| System failures | Health destination and/or Owners |
| Daily Admin Brief | Owner-configured Admin Operations or Reports chat/topic |

Telegram forum deliveries must include both chat ID and `message_thread_id`. Private records
must never be routed to the Main or Sellers community chat. Failures create audit events and
Needs Attention items.

Immediate alerts are reserved for three-day participation follow-up, new registrations,
Away Notices needing attention, post-deadline POP exceptions, actionable warnings or strikes,
new or escalated support, routing/delivery failure, critical health failure, and Owner Review.
Healthy participation and ordinary POP receipts remain quiet and appear in queues and summaries.

The Daily Admin Brief uses a durable Eastern-calendar-date claim. A restart cannot send a second
normal brief for the same date. A failed brief is preserved with a safe reference and Owners are
notified privately once.

`bot/routing.py` is the single destination map. Missing or failed destinations are stored
before they are surfaced to Owners, so operational events are not silently lost.
