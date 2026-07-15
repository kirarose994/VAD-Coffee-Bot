# Command Reference

The visible product is button-driven. `/start` is the primary entry point. Existing slash
commands remain fallback/diagnostic interfaces and must enforce the same permissions.

Creator fallbacks cover registration, availability, Away Notices, POP/status, timeline, and
Contact Admin. Operational fallbacks cover queues, creator reports/search, warnings,
templates, announcements, and calendar. Owner-only fallbacks cover complete audit, protected
roles/settings, exports, restore, and health.

`/groupid` and `/topicid` are owner-only fallbacks. Temporary `/myid`, `/chatid`, and
`/threadid` handlers are not registered by the active application. Use Owner Setup → Verify
Current Chat/Topic instead. Commands must never print tokens or environment values.

At startup, the bot registers short Telegram command menus for private chats, groups, and
group administrators. Group commands open the bot privately and never render personal status,
POP, Away Notice, timeline, or operational information in a public chat. Command visibility is
only a convenience; every destination still enforces role and permission checks server-side.
