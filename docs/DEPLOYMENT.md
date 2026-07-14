# Deployment

This repository’s Replit workflow runs `cd bot && python main.py`. Deploy only reviewed code
from the intended main commit.

1. Stop all competing Telegram pollers.
2. Back up the database and record the current commit.
3. Pull reviewed `main`.
4. Confirm required Secrets without printing their values.
5. Start the workflow and verify one polling process remains healthy.
6. Test `/start` privately for every role, then verify routing in controlled topics.

This branch must not be deployed until its draft pull request is reviewed and merged manually.
