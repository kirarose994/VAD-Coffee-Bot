# Permission System

Authorization uses immutable Telegram numeric IDs. Role order is Owner, Lead Admin, Admin,
then unprivileged community member. Creator and Buyer are product identities, not privileged
administrative roles.

Owners receive every permission. Lead Admin defaults cover operational reviews and creator
management. Admin defaults cover reports, moderation, notes, and messaging. Individual
allow-lists may narrow or extend non-owner permissions, but only Owners can access Setup,
full audit, protected archive/restore, exports, security health, and access management.

Buttons are filtered for usability; `has_permission()` and owner checks remain the security
boundary for every callback and command.
