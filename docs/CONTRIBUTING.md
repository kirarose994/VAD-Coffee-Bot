# Contributing

Create a feature branch; never change live Replit state while developing. Keep secrets and
databases out of Git. Use `apply_patch`-style focused edits, preserve user data, and add safe
additive migrations when schema changes are unavoidable.

Every behavior change requires tests and synchronized documentation. Run the full unittest
suite, Python compilation, diff validation, and secret scanning. Review role visibility,
server authorization, callback replay, routing, Eastern Time, idempotency, audit, backup, and
rollback implications before requesting review.

Pull requests remain draft until validation is complete. Never merge or deploy automatically.
