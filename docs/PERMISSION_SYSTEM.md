# Permission System

Authorization uses immutable Telegram numeric IDs. Public roles are additive: every Owner is
also an Admin and Creator, every Admin is also a Creator, and Creator-only members have no
administrative access. The legacy Lead Admin tier remains an Admin permission bundle for
backward compatibility; it is not a separate identity.

Owners receive every permission. Lead Admin defaults cover operational reviews and creator
management. Admin defaults cover reports, moderation, notes, and messaging. Individual
allow-lists may narrow or extend non-owner permissions, but only Owners can access Setup,
full audit, protected archive/restore, exports, security health, and access management.

Buttons are filtered for usability; `has_permission()` and owner checks remain the security
boundary for every callback and command.

The `user_roles` table stores attached memberships and their active/removal history. Secure
bootstrap IDs and audited Owner changes are synchronized without replacing creator records.
