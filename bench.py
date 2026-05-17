#!/usr/bin/env python3
"""Run multiple planners on the same seed set and print a comparison table.

Usage:
    python bench.py
    python bench.py --maps 50 --seed-base 0
    python bench.py --planners factory_plan plans.v0_naive plans.v1_multi_lane
    python bench.py --maps 100 --label-suffix v1-test

Each planner runs through eval.py with --no-png (fast) and appends one row
to results/runs.jsonl, then a sorted table is printed. The leader is whichever
planner has the highest mean_score over the shared seed set.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_PLANNERS = [
    "plans.v0_naive",
    "plans.v1_multi_lane",
    "factory_plan",
]

HERE = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Auto Factory planner bench")
    ap.add_argument("--maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument(
        "--planners",
        nargs="+",
        default=DEFAULT_PLANNERS,
        help="dotted module paths to compare",
    )
    ap.add_argument(
        "--label-suffix",
        default="bench",
        help="appended to each planner's --label tag in runs.jsonl",
    )
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--keep-png", action="store_true", help="generate PNGs too")
    return ap.parse_args()


def run_eval(planner: str, args: argparse.Namespace) -> dict:
    cmd = [
        sys.executable,
        str(HERE / "eval.py"),
        "--planner", planner,
        "--maps", str(args.maps),
        "--seed-base", str(args.seed_base),
        "--ticks", str(args.ticks),
        "--out-dir", args.out_dir,
        "--label", f"{planner}:{args.label_suffix}",
    ]
    if not args.keep_png:
        cmd.append("--no-png")

    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"eval.py failed for planner={planner}")

    # Pull the JUST-appended row from runs.jsonl (last line).
    runs = (HERE / args.out_dir / "runs.jsonl").read_text().splitlines()
    return json.loads(runs[-1])


def main() -> int:
    args = parse_args()
    rows = []
    for planner in args.planners:
        print(f"... running {planner}")
        rows.append(run_eval(planner, args))

    rows.sort(key=lambda r: -r["summary"]["mean_score"])

    print(
        f"\n{'planner':<28} {'mean':>8} {'median':>8} {'best':>8} {'worst':>8} "
        f"{'valid':>6} {'meanWPM':>8} {'maxWPM':>8}"
    )
    print("-" * 90)
    for r in rows:
        s = r["summary"]
        print(
            f"{r['planner']:<28} "
            f"{s['mean_score']:>8.2f} {s['median_score']:>8.2f} "
            f"{s['best_score']:>8.2f} {s['worst_score']:>8.2f} "
            f"{s['valid']:>6d} {s['valid_mean_wpm']:>8.2f} {s['valid_max_wpm']:>8.2f}"
        )

    leader = rows[0]
    print(
        f"\nLeader: {leader['planner']} "
        f"(mean={leader['summary']['mean_score']}, "
        f"hash={leader['planner_hash']})"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
