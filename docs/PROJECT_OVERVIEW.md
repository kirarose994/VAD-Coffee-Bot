# Project Overview

The VAD Operations Bot is a private Telegram application for a creator community. It gives
creators a supportive self-service hub and gives authorized operators queues, reports, and
audited tools appropriate to their role.

Its central design rule is separation: participation is meaningful text in configured Main
Group topics; POP is proof submitted in a configured Sellers Group topic. POP never earns
participation credit. Only approved creator records are eligible for either system.

The system uses immutable Telegram numeric IDs for identity, SQLite for durable state,
`America/New_York` for community time, and Telegram inline buttons for guided workflows.
