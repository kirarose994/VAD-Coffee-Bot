# Audit System

## System incidents

Transient `httpcore.ReadError`, `httpx.ReadError`, and Telegram `NetworkError` failures share one
open incident fingerprint. Repeated occurrences update the incident’s last-seen time and count
without creating duplicate audit entries or Owner alerts. A successful routed Telegram send or
recovery probe resolves the incident. Exception type, sanitized message, and traceback remain
Owner-visible. Non-network exceptions continue to create distinct immediate error records.

Important actions append to `audit_events`: registrations, approval decisions, identity
refreshes, availability, Away Notices, POP, participation decisions, reminders, warnings,
notes, roles, settings, exports, deletion, restoration, announcements, and delivery failures.

Entries carry Eastern timestamp, actor and role when known, action, target, previous/new
values, reason, source location, related records, result, and safe error reference. Owners see
the complete readable log. Other roles cannot alter, erase, or hide audit evidence.
