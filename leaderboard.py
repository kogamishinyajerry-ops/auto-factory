#!/usr/bin/env python3
"""Read results/runs.jsonl and print a leaderboard.

Each eval invocation appends one JSON line. This script groups them by
(planner, seed_base, n_maps, ticks) and shows the latest run per planner,
sorted by mean_score.

Usage:
    python leaderboard.py
    python leaderboard.py --all       # show every row, not just the latest per planner
    python leaderboard.py --top 10
    python leaderboard.py --since 2026-05-17T12:00:00Z
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="results/runs.jsonl")
    ap.add_argument(
        "--all",
        action="store_true",
        help="list every row instead of latest-per-planner",
    )
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--since", default=None, help="ISO timestamp; only rows after this")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.runs)
    if not path.exists():
        print(f"no run log at {path}")
        return 1

    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if args.since:
        rows = [r for r in rows if r.get("ts", "") >= args.since]

    if not args.all:
        # keep only the latest row per planner+seed_base+n_maps key
        seen: dict[tuple, dict] = {}
        for r in rows:
            key = (r["planner"], r.get("seed_base", 0), r["n_maps"])
            if key not in seen or r["ts"] > seen[key]["ts"]:
                seen[key] = r
        rows = list(seen.values())

    rows.sort(key=lambda r: -r["summary"]["mean_score"])
    rows = rows[: args.top]

    if not rows:
        print("no rows match")
        return 0

    print(
        f"{'#':>3} {'planner':<28} {'mean':>7} {'median':>7} {'best':>7} {'WPM~':>6} {'WPMmax':>7} {'n':>4} {'ts':<20} {'hash':<24}"
    )
    print("-" * 120)
    for i, r in enumerate(rows, 1):
        s = r["summary"]
        print(
            f"{i:>3} {r['planner']:<28} "
            f"{s['mean_score']:>7.2f} {s['median_score']:>7.2f} {s['best_score']:>7.2f} "
            f"{s['valid_mean_wpm']:>6.2f} {s['valid_max_wpm']:>7.2f} "
            f"{r['n_maps']:>4} {r['ts']:<20} {r.get('planner_hash', '?'):<24}"
        )

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
