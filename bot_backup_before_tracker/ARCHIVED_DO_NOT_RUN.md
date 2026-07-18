# Historical archive — do not run

This directory preserves the former Coffee ordering implementation for historical reference.
It is not a production application, workflow, fallback, or recovery launcher.

Both historical `main.py` entry points exit immediately when executed directly. The only
supported VAD Operations Bot entry point is:

```text
cd bot && python main.py
```

Do not re-enable an archived launcher. A second process using the Bot API token can conflict
with the production poller, and this archive does not participate in the active singleton
lease.
