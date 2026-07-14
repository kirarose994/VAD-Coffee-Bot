# Security

- Secrets, bot tokens, private keys, databases, and exports must never be committed.
- Telegram numeric user ID is the stable authorization identity.
- Every command, callback, record lookup, export, restore, role change, and setting change
  must authorize server-side.
- Callback nonces prevent expired/reused actions; database uniqueness prevents duplicate taps.
- Owners alone receive full actor identities, protected history, exports, restore, and Setup.
- Audit events are append-oriented and cannot be reset through the bot.
- Errors shown to Telegram contain safe references, never traces or secret values.

Rotate any credential found in Git history, remove it from history, and review access logs.
