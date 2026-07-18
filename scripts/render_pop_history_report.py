"""Render an existing scanner JSON file with read-only creator identity lookups."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))

from pop_history_report import OwnerReportError, build_owner_report, render_owner_report  # noqa: E402


def arguments() -> argparse.Namespace:
    parser=argparse.ArgumentParser(description="Read-only grouped POP history report")
    parser.add_argument("--report",type=Path,default=ROOT / "pop_history_report.json")
    parser.add_argument("--creator-db",type=Path,default=ROOT / "bot" / "vad_tracker.db")
    return parser.parse_args()


def main(args: argparse.Namespace | None = None) -> int:
    args=args or arguments()
    try:
        with args.report.open(encoding="utf-8") as source:
            scan_report=json.load(source)
        report=build_owner_report(scan_report,creator_database=args.creator_db)
    except (OSError,json.JSONDecodeError,OwnerReportError) as exc:
        print(f"Owner report refused safely: {type(exc).__name__}",file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Owner report failed safely: {type(exc).__name__}",file=sys.stderr)
        return 1
    print(render_owner_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
