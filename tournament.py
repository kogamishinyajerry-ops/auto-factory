#!/usr/bin/env python3
"""Parallel iterate workers + diversity merge.

Spawn K iterate.py subprocesses in parallel, each with its own mutation
RNG seed and its own factory_plan_w<i>.py file. After they all hit their
wall-clock budget, union the strategies they discovered into a single
meta-portfolio and write it back to factory_plan.py.

The bet: each worker explores a different region of the search space.
Merging their best strategies builds a more diverse portfolio than any
single worker found alone.

Usage:
    python tournament.py                              # K=4, 90s each, parallel
    python tournament.py --workers 6 --budget-sec 120 --eval-maps 50
    python tournament.py --no-merge                   # just report; don't touch factory_plan.py

After: results/_workers/w<i>/iterate.jsonl holds each worker's curve;
results/tournament.json holds the merge decision.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Import iterate.py's CONFIG io and signature helper.
sys.path.insert(0, str(HERE))
import iterate  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget-sec", type=float, default=90.0)
    ap.add_argument("--eval-maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=100)
    ap.add_argument(
        "--meta-cap",
        type=int,
        default=12,
        help="max strategies kept in the merged portfolio (controls plan() cost)",
    )
    ap.add_argument(
        "--no-merge",
        action="store_true",
        help="run workers and report, but don't overwrite factory_plan.py",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    workers_dir = HERE / "results" / "_workers"
    workers_dir.mkdir(parents=True, exist_ok=True)

    procs = []
    for i in range(args.workers):
        wdir = workers_dir / f"w{i}"
        wdir.mkdir(parents=True, exist_ok=True)
        target = HERE / f"factory_plan_w{i}.py"
        shutil.copy(HERE / "factory_plan.py", target)
        # Reset that worker's iterate.jsonl so progress.py can plot it cleanly
        log_path = wdir / "iterate.jsonl"
        log_path.unlink(missing_ok=True)

        cmd = [
            sys.executable,
            str(HERE / "iterate.py"),
            "--budget-sec", str(args.budget_sec),
            "--eval-maps", str(args.eval_maps),
            "--seed", str(args.seed_base + i),
            "--reset",
            "--target-file", str(target),
            "--planner-name", f"factory_plan_w{i}",
            "--log-file", str(log_path),
            "--eval-out-dir", str(wdir),
            "--quiet",
        ]
        stdout_log = (wdir / "stdout.log").open("w")
        p = subprocess.Popen(cmd, stdout=stdout_log, stderr=subprocess.STDOUT, cwd=HERE)
        procs.append({"i": i, "proc": p, "target": target, "wdir": wdir, "stdout": stdout_log})
        print(f"  spawned worker {i}  pid={p.pid}  seed={args.seed_base + i}")

    print(f"\nWaiting for {args.workers} workers ({args.budget_sec}s budget each, parallel)…")
    start = time.time()
    for w in procs:
        rc = w["proc"].wait()
        w["stdout"].close()
        print(
            f"  worker {w['i']:>2} done in {time.time() - start:>5.1f}s (rc={rc})"
        )

    # Collect each worker's discovered portfolio + final score.
    worker_results = []
    all_strategies: list[dict] = []
    for w in procs:
        cfg = iterate.read_config(w["target"])
        # parse the worker's stdout for "Final {N}-map bench... mean: X"
        text = (w["wdir"] / "stdout.log").read_text()
        final_line = next(
            (ln for ln in text.splitlines() if "(50 maps) mean" in ln or "(maps) mean" in ln),
            "",
        )
        try:
            final_score = float(final_line.split("mean:")[-1].strip())
        except (ValueError, IndexError):
            final_score = float("nan")
        worker_results.append(
            {
                "worker": w["i"],
                "score": final_score,
                "n_strategies": len(cfg["strategies"]),
                "strategies": cfg["strategies"],
            }
        )
        for s in cfg["strategies"]:
            all_strategies.append(s)
        print(
            f"  worker {w['i']:>2} found {len(cfg['strategies'])} strategies, "
            f"final score = {final_score:.3f}"
        )

    # Dedup strategies by signature (the same one as iterate.py uses).
    seen: set[tuple] = set()
    unique: list[dict] = []
    for s in all_strategies:
        key = tuple((k, repr(v)) for k, v in sorted(s.items()))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    print(
        f"\nMerged {len(all_strategies)} → {len(unique)} unique strategies"
    )

    # If too many, score each individually and keep top.
    if len(unique) > args.meta_cap:
        print(f"  scoring each strategy individually to pick top {args.meta_cap}…")
        individual_scores = []
        for s in unique:
            cfg_single = {"strategies": [s]}
            iterate.write_config(cfg_single, path=HERE / "factory_plan.py")
            score = iterate.evaluate(args.eval_maps, "factory_plan", "results")
            individual_scores.append((score, s))
        individual_scores.sort(key=lambda x: -x[0])
        unique = [s for _, s in individual_scores[: args.meta_cap]]
        print(
            f"  top-{args.meta_cap} individual scores: "
            + ", ".join(f"{sc:.2f}" for sc, _ in individual_scores[: args.meta_cap])
        )

    # Write merged portfolio to factory_plan.py and re-bench.
    meta_cfg = {"strategies": unique}
    meta_score = float("nan")
    if not args.no_merge:
        iterate.write_config(meta_cfg, path=HERE / "factory_plan.py")
        print(f"\nMerged portfolio of {len(unique)} strategies written to factory_plan.py")
        print(f"Final {args.eval_maps}-map bench of merged portfolio…")
        meta_score = iterate.evaluate(args.eval_maps, "factory_plan", "results")
        print(f"  factory_plan (merged) mean: {meta_score:.3f}")

    # Persist tournament summary.
    summary = {
        "workers": args.workers,
        "budget_sec": args.budget_sec,
        "eval_maps": args.eval_maps,
        "seed_base": args.seed_base,
        "elapsed_sec": round(time.time() - start, 1),
        "worker_results": worker_results,
        "n_merged_strategies": len(unique),
        "merged_score": meta_score,
        "merged_strategies": unique,
    }
    (workers_dir.parent / "tournament.json").write_text(json.dumps(summary, indent=2))
    print(f"\n  summary -> {workers_dir.parent / 'tournament.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
