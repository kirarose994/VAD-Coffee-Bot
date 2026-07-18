# Security

- Secrets, bot tokens, private keys, databases, and exports must never be committed.
- Telegram numeric user ID is the stable authorization identity.
- Every command, callback, record lookup, export, restore, role change, and setting change
  must authorize server-side.
- Callback nonces prevent expired/reused actions; database uniqueness prevents duplicate taps.
- Owners alone receive full actor identities, protected history, exports, restore, and Setup.
- Audit events are append-oriented and cannot be reset through the bot.
- Errors shown to Telegram contain safe references, never traces or secret values.
- POP URLs are recognized from Telegram entities or local syntax parsing only. The bot never
  opens, fetches, executes, scrapes, or stores the full URL.
- POP proof is accepted only for an active creator in the configured Sellers Chat and POP thread.
  Edited messages repeat every server-side identity, location, day, and week check.
- Update IDs and source chat/message/thread references support idempotency. POP metadata does not
  retain submitted URLs, captions, descriptions, or image files, and links are never fetched.
- Split evidence is correlated only by immutable creator ID, exact numeric location, week, and a
  five-minute window; evidence from different creators cannot be combined.
- Startup acquires the schema-v13 `telegram_bot_api_poller` lease before contacting Telegram.
  Atomic acquisition, owner-token heartbeats, expiry, and owner-checked release prevent two
  processes sharing one SQLite file from polling simultaneously. Lease verification fails closed.
- The lease does not coordinate separate Autoscale filesystems or copied databases. Singleton
  hosting is still required. Pending-update deletion remains disabled, and evidence, update,
  alert, and Owner-summary claims remain database-deduplicated across restarts.
- Telegram does not reliably report arbitrary group-message deletion or provide general
  historical-message lookup to ordinary bots. An inconclusive 24-hour preservation check creates
  a deduplicated Admin review item, never an automatic accusation, warning, or strike. Confirmed
  early removal requires direct Admin evidence and an explicit confirmation.
- Recovery confidence is conservative: no prior heartbeat is **Unknown**, and an outage beyond
  the conservative queue window is **Partial**. Neither state is presented as complete recovery.

- Schema v13 keeps Owner-entered historical decisions separate from Telegram-observed evidence.
  It never fabricates chat or message IDs. Nonce-protected previews, repeated Owner authorization,
  a second overwrite confirmation, request-key idempotency, and append-only audit events protect
  reconciliation. Regular Admins have no reconciliation mutation path.
- Late-alert claims are atomic per canonical creator/week record. Their content is informational
  and routes only to the existing authorized POP-review destination; no warning or strike is created.

Rotate any credential found in Git history, remove it from history, and review access logs.
