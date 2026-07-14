# Participation Engine

Approved creators should not go more than two full days without meaningful participation in the
configured Main VAD discussion area. A friendly reminder is triggered at two days. At three full
days without meaningful participation, and without an active Away Notice, the Admin team receives
a follow-up alert. The purpose is to help keep the community lively so members have a reason to
come back—not to reward simple check-ins.

Meaningful participation means contributing to genuine conversation that helps keep the
community active and engaging. Approved creators can respond thoughtfully, ask questions,
join discussions, offer help, or otherwise add value. The purpose is not to make someone
post every two days; it is to help keep the community lively so members have a reason to
come back.

Simple check-ins, greetings, emojis, stickers, photos without meaningful context, repeated
messages, promotional posts, and similar filler do not satisfy the participation requirement.

Approved creators should not go more than two full days without meaningful participation in
the Main VAD discussion. After two full days, the bot sends a friendly reminder. After three
full days, if no meaningful participation or approved Away Notice exists, the bot notifies
the Admin team for supportive follow-up.

Participation is evaluated only when chat and topic match the owner-managed allow-list. The
initial Participation Group is the Main VAD supergroup (`-1003543892255`); its General topic
ID must be detected, never guessed.

The sender must have an approved, unarchived creator record and no active approved absence.
Buyer identities and administrators without approved creator profiles never count. POP-topic
media returns through the POP workflow and never reaches participation classification.

`engagement.classify()` rejects non-text media, emoji/punctuation, greetings, promotions,
short filler, and canonical repeats. Minimum words, characters, and repeat window are Owner
Setup settings. Accepted messages update the participation anchor idempotently.
