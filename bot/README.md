# VAD Operations Bot Runtime

This directory contains the active Telegram application. Start it with:

```text
cd bot && python main.py
```

The application provides role-separated Owner, Lead Admin, Admin, Creator, and Buyer
interfaces. Participation is meaningful text from approved creators in configured Main Group
topics. Thursday POP is a separate Sellers Group/topic workflow and never counts as
participation.

Bootstrap secrets and IDs are read by `config.py`. Owner-approved operational settings are
stored in SQLite by `runtime_config.py`, audited, and restored after restart. Temporary setup
handlers are not registered; Owners use Setup → Verify Current Chat/Topic.

The historical ordering application exists only under `bot_backup_before_tracker/`. Nothing
in this active directory imports or registers it.

See [the documentation index](../docs/README.md) for architecture, configuration, roles,
routing, deployment, security, backup, troubleshooting, and extension guidance.
