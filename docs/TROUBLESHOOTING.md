# Troubleshooting

## Temporary Telegram connection incidents

Short-lived Telegram read failures are retried with bounded exponential backoff. If retries are
exhausted, the original delivery failure remains stored and one grouped system incident is opened.
Owners can review first seen, last seen, occurrence count, status, and sanitized traceback under
Audit Log → System Errors. A successful Telegram recovery check marks the incident Resolved.

## Approved creators are not receiving participation credit

Open Owner Home → Setup & Readiness and Participation Monitor. Confirm the displayed Main Group
and topic match the message location, and check **Can read ordinary messages**. Telegram privacy
mode must be disabled through BotFather, or the bot must be an administrator in the Main Group.
After one accepted meaningful message, Last Message Detected, Last Meaningful Participation,
ordinary-message access, and Participation Monitor automatically become verified. Commands,
greetings, short filler, promotional links, media without meaningful context, and repeated text
remain intentionally ignored.

## Bot receives no messages

Confirm exactly one polling process. Telegram `Conflict: terminated by other getUpdates`
means another workflow or deployment uses the same token.

## Participation does not count

Verify creator status is active, no Away Notice is active, and current chat/topic exactly
matches Setup. Check meaningful-message rejection rules.

## Telegram still suggests commands from the retired bot

Open Owner Home → Setup & Readiness → Telegram Command Menus and confirm that Private Chats,
Groups, and Group Administrators are all Ready. Telegram clients may temporarily cache command
suggestions for another bot that remains in the group. After the new bot’s three scopes are Ready,
remove the retired bot from the group to eliminate its command suggestions. Active registration
uses the username returned by Telegram and has no hard-coded old-bot username dependency.

## Registration looks wrong

Open Registration Status. Telegram ID prevents duplicates. Check approval state, archive
state, directory visibility, and community-member identity consistency. Archived records must
be restored by an Owner; repeat registration does not overwrite approval.

## POP looks missing too early

Verify timezone and cutoff, then confirm every screen uses `pop_policy.py`. Missing is valid
only after the due cutoff.

## POP after an outage

Open **Owner Tools → Recovery → POP Recovery Report**. Complete means retained Telegram updates
were processed inside the conservative recovery window. Partial or Unknown requires manual
review. Never infer proof from an unavailable message or claim arbitrary group-history retrieval.

## Delivery failed

Verify bot membership, permissions, chat ID, and topic ID in Setup. Review the safe error in
Needs Attention/Audit.
