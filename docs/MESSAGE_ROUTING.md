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

Telegram forum deliveries must include both chat ID and `message_thread_id`. Private records
must never be routed to the Main or Sellers community chat. Failures create audit events and
Needs Attention items.

`bot/routing.py` is the single destination map. Missing or failed destinations are stored
before they are surfaced to Owners, so operational events are not silently lost.
