# Backup and Recovery

Stop the bot before copying `bot/vad_tracker.db` and any `-wal` or `-shm` companions. Store a
dated copy outside the repository with the deployed commit ID and configuration-key inventory.

To recover, stop polling, preserve the failed database for diagnosis, restore the complete
backup set, return to the recorded commit, verify configuration, and start exactly one poller.
Run Owner Health, creator counts, audit, and routing checks before reopening normal use.

Never repair production by deleting audit, creator, POP, or engagement history.
