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
- Telegram does not reliably report arbitrary group-message deletion or provide general
  historical-message lookup to ordinary bots. An inconclusive 24-hour preservation check creates
  a deduplicated Admin review item, never an automatic accusation, warning, or strike. Confirmed
  early removal requires direct Admin evidence and an explicit confirmation.

Rotate any credential found in Git history, remove it from history, and review access logs.
