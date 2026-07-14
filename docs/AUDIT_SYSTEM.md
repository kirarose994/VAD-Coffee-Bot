# Audit System

Important actions append to `audit_events`: registrations, approval decisions, identity
refreshes, availability, Away Notices, POP, participation decisions, reminders, warnings,
notes, roles, settings, exports, deletion, restoration, announcements, and delivery failures.

Entries carry Eastern timestamp, actor and role when known, action, target, previous/new
values, reason, source location, related records, result, and safe error reference. Owners see
the complete readable log. Other roles cannot alter, erase, or hide audit evidence.
