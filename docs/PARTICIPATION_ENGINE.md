# Participation Engine

Approved creators should not go more than two full days without meaningful participation in the
configured Main VAD discussion area. A friendly reminder is triggered at two days. At three full
days without meaningful participation, and without an active Away Notice, the Admin team receives
a follow-up alert. The purpose is to help keep the community lively so members have a reason to
come back—not to reward simple check-ins.

The ordinary text observer is registered in dispatcher group 10 with `TEXT` excluding commands.
Startup records Telegram’s group-message privacy capability, and the Owner verification screens
show whether normal group messages are available. A real accepted participation event updates both
the creator timestamp and readiness evidence; readiness no longer depends solely on synthetic tests.

Meaningful participation means contributing to genuine conversation that helps keep the
community active and engaging. Approved creators can respond thoughtfully, ask questions,
join discussions, offer help, or otherwise add value. The purpose is not to make someone
post every two days; it is to help keep the community lively so members have a reason to
come back.

Simple check-ins, greetings, emojis, stickers, photos without meaningful context, repeated
messages, promotional posts, and similar filler do not satisfy the participation requirement.

Telegram voice messages and uploaded audio of at least five seconds may count without
speech-to-text when the creator, location, Away Notice, duplicate-file, and promotional-caption
checks pass. Shorter audio is recorded as `audio_too_short` and does not count.

Approved creators should not go more than two full days without meaningful participation in
the Main VAD discussion. After two full days, the bot sends a friendly reminder. After three
full days, if no meaningful participation or approved Away Notice exists, the bot notifies
the Admin team for supportive follow-up.

Participation is evaluated only when chat and topic match the owner-managed allow-list. The
initial Participation Group is the Main VAD supergroup (`-1003543892255`). Telegram currently
delivers its intended General discussion area with no `message_thread_id`, so the verified
General-only configuration is represented by an empty participation-topic allow-list. Numbered
Admin routing topics, including the reports topic, must never be reused for participation.

Owners can explicitly select **Use General for Participation** from Telegram Locations or the
Participation Monitor. This audited action replaces any incorrect numbered participation topics
with General-only; it does not broaden tracking to every forum topic.

The sender must have an approved, unarchived creator record and no active approved absence.
Buyer identities and administrators without approved creator profiles never count. POP-topic
media returns through the POP workflow and never reaches participation classification.

`engagement.classify()` rejects non-text media, emoji/punctuation, greetings, promotions,
short filler, and canonical repeats. Minimum words, characters, and repeat window are Owner
Setup settings. Accepted messages update the participation anchor idempotently.
