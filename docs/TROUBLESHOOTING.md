# Troubleshooting

## Temporary Telegram connection incidents

Short-lived Telegram read failures are retried with bounded exponential backoff. If retries are
exhausted, the original delivery failure remains stored and one grouped system incident is opened.
Owners can review first seen, last seen, occurrence count, status, and sanitized traceback under
Audit Log → System Errors. A successful Telegram recovery check marks the incident Resolved.

## Bot receives no messages

Confirm exactly one polling process. Telegram `Conflict: terminated by other getUpdates`
means another workflow or deployment uses the same token.

## Participation does not count

Verify creator status is active, no Away Notice is active, and current chat/topic exactly
matches Setup. Check meaningful-message rejection rules.

## Registration looks wrong

Open Registration Status. Telegram ID prevents duplicates. Check approval state, archive
state, directory visibility, and community-member identity consistency. Archived records must
be restored by an Owner; repeat registration does not overwrite approval.

## POP looks missing too early

Verify timezone and cutoff, then confirm every screen uses `pop_policy.py`. Missing is valid
only after the due cutoff.

## Delivery failed

Verify bot membership, permissions, chat ID, and topic ID in Setup. Review the safe error in
Needs Attention/Audit.
