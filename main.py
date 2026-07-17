"""Convenience launcher for the VAD Operations Bot.

Replit uses ``cd bot && python main.py``. This wrapper makes ``python main.py`` from the
repository root behave consistently for developers.
"""

from bot.main import main


if __name__ == "__main__":
    raise SystemExit(main())
