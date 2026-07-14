# Backup and Recovery

The bot does not assume Replit or another provider created a database backup. Owner Readiness
shows **Needs Setup** until a recent backup is explicitly tracked. Stop every bot process
before copying `bot/vad_tracker.db` and any `-wal` and `-shm` companions to private storage.
Never commit a database backup to GitHub.

Bot code is stored in GitHub, but creator history and operational records are stored in the
database. Both are needed for a full recovery.

Stop the bot before copying `bot/vad_tracker.db` and any `-wal` or `-shm` companions. Store a
dated copy outside the repository with the deployed commit ID and configuration-key inventory.

To recover, stop polling, preserve the failed database for diagnosis, restore the complete
backup set, return to the recorded commit, verify configuration, and start exactly one poller.
Run Owner Health, creator counts, audit, and routing checks before reopening normal use.

Never repair production by deleting audit, creator, POP, or engagement history.
