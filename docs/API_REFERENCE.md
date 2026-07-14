# API Reference

This project currently exposes no public HTTP API. Its internal service boundaries are Python
functions:

- `database.*`: all durable reads, mutations, migrations, audit, and idempotency claims.
- `permissions.role_for/has_permission`: role and capability decisions.
- `engagement.classify`: deterministic message decision.
- `pop_policy.current_period/calculate_status`: centralized POP state.
- `runtime_config.apply_persisted_settings/persist_setting`: audited operational settings.
- `tracker.participation_enabled`: chat/topic allow-list decision.

Treat these as internal APIs: preserve parameters, return semantics, idempotency, and tests
when extending them.
