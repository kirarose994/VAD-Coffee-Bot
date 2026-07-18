"""Owner-gated CLI for one read-only Telegram POP history scan."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))

from pop_history_scanner import (  # noqa: E402
    PopHistoryScanConfig,
    ScanScopeError,
    ScanValidationError,
    scan_pop_history,
)
from pop_history_report import build_owner_report, render_owner_report  # noqa: E402


def _timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use ISO-8601 with a timezone offset") from exc
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return result


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Owner POP history dry run")
    parser.add_argument("--owner-id", required=True, type=int)
    parser.add_argument("--start", required=True, type=_timestamp)
    parser.add_argument("--end", required=True, type=_timestamp)
    parser.add_argument("--owner-report", action="store_true",
        help="group results by creator using a strictly read-only database lookup")
    parser.add_argument("--creator-db", type=Path, default=ROOT / "bot" / "vad_tracker.db",
        help="creator database opened with SQLite mode=ro when --owner-report is used")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    try:
        report = await scan_pop_history(
            PopHistoryScanConfig.from_env(),
            owner_id=args.owner_id,
            start=args.start,
            end=args.end,
        )
    except (ScanValidationError, ScanScopeError) as exc:
        print(f"Scan refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not echo third-party exception details: authentication and transport
        # failures must never risk reflecting session or credential material.
        print(f"Scan failed safely: {type(exc).__name__}", file=sys.stderr)
        return 1
    if args.owner_report:
        try:
            owner_report=build_owner_report(report,creator_database=args.creator_db)
        except Exception as exc:
            print(f"Owner report failed safely: {type(exc).__name__}",file=sys.stderr)
            return 1
        print(render_owner_report(owner_report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(arguments())))
