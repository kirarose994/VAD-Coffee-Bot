# Participation Engine

Participation is evaluated only when chat and topic match the owner-managed allow-list. The
initial Participation Group is the Main VAD supergroup (`-1003543892255`); its General topic
ID must be detected, never guessed.

The sender must have an approved, unarchived creator record and no active approved absence.
Buyer identities and administrators without approved creator profiles never count. POP-topic
media returns through the POP workflow and never reaches participation classification.

`engagement.classify()` rejects non-text media, emoji/punctuation, greetings, promotions,
short filler, and canonical repeats. Minimum words, characters, and repeat window are Owner
Setup settings. Accepted messages update the participation anchor idempotently.
