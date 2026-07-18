# Deployment

This repository’s Replit workflow runs `cd bot && python main.py`. Deploy only reviewed code
from the intended main commit.

1. Stop all competing Telegram pollers.
2. Back up the database and record the current commit.
3. Pull reviewed `main`.
4. Confirm required Secrets without printing their values.
5. Start the workflow and verify one polling process remains healthy.
6. Test `/start` privately for every role, then verify routing in controlled topics.

## Bot API polling singleton

Schema version 13 adds a database-backed lease named `telegram_bot_api_poller`. Startup acquires
the lease before building the Telegram application or beginning long polling. A second process
using the same SQLite database exits without contacting Telegram while the first lease remains
live. The owner process refreshes the lease every 30 seconds; an unverifiable heartbeat stops
polling, and a clean shutdown releases only its own lease. A crashed process can be replaced after
the 90-second lease expires.

The lease protects processes that share the same database file. It does **not** coordinate
Autoscale replicas with separate filesystems, a copied database, another host, or an archived bot
using a different database. Production still requires exactly one Workspace workflow or one
singleton deployment. Do not run Workspace Run and a published deployment together.

Startup logs one sanitized identity line containing application name, commit when available,
process-instance ID, SQLite path, lease result, Eastern polling time, and a short host/source
label. It never prints the bot token or the full environment.

The historical launchers under `bot_backup_before_tracker/` are deliberately disabled and are
not fallback entry points.

This branch must not be deployed until its draft pull request is reviewed and merged manually.
