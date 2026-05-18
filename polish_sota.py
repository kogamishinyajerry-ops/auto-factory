#!/usr/bin/env python3
"""Focused polish loop for the current factory_plan.py SOTA.

iterate.py's mutator is built for exploration (random restarts, add/
remove strategies, replace-one). For a SOTA polish we want EXPLOITATION:
preserve the portfolio size and structure, only tweak individual keys.

This script reads the current CONFIG, runs a custom polish loop that
only does single-key tweaks (and occasional replace-one), 50-map eval
for low noise, greedy-accept. Result is written back as the new SOTA
if and only if it strictly beats the starting score.

Usage:
    python polish_sota.py
    python polish_sota.py --budget-sec 300 --eval-maps 50 --max-iters 60
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import iterate  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec", type=float, default=300.0)
    ap.add_argument("--max-iters", type=int, default=60)
    ap.add_argument("--eval-maps", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--log-file", default="results/polish.jsonl")
    ap.add_argument("--p-replace", type=float, default=0.15,
                    help="probability of replace-one (vs single-key tweak)")
    return ap.parse_args()


def polish_mutate(cfg: dict, rng: random.Random, p_replace: float) -> dict:
    """Tweak-or-replace only. Preserves portfolio size."""
    strategies = [dict(s) for s in cfg["strategies"]]
    n = len(strategies)
    if n == 0:
        return cfg
    i = rng.randrange(n)
    if rng.random() < p_replace:
        # replace one strategy with a fresh random one
        strategies[i] = iterate._random_strategy(rng)
    else:
        # tweak one key of one strategy
        strategies[i] = iterate._mutate_strategy(strategies[i], rng)

    # dedup within portfolio (rare with this mutator but possible)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for s in strategies:
        key = tuple((k, repr(v)) for k, v in sorted(s.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    return {"strategies": deduped}


def main() -> int:
    args = parse_args()
    log_path = HERE / args.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a")
    rng = random.Random(args.seed)

    starting_cfg = iterate.read_config()
    print(f"polishing portfolio of {len(starting_cfg['strategies'])} strategies")
    print(f"  budget={args.budget_sec}s  max_iters={args.max_iters}  "
          f"eval_maps={args.eval_maps}  p_replace={args.p_replace}")

    best_cfg = starting_cfg
    iterate.write_config(best_cfg)
    best_score = iterate.evaluate(args.eval_maps, "factory_plan", "results")
    print(f"  starting bench: {best_score:.3f}\n")

    log_fh.write(
        json.dumps({
            "ts": iterate._now_iso(),
            "iter": 0,
            "score": best_score,
            "best": best_score,
            "accept": True,
            "source": "polish_baseline",
        }) + "\n"
    )
    log_fh.flush()

    print(f"{'iter':>4}  {'src':<8}  {'delta':>7}  {'score':>7}  {'best':>7}  {'acc':<4}")
    print("-" * 60)

    tried: set[tuple] = {iterate._config_signature(best_cfg)}
    start = time.time()
    accepts = 0
    for i in range(1, args.max_iters + 1):
        elapsed = time.time() - start
        if elapsed > args.budget_sec:
            print(f"\nbudget exhausted at iter {i - 1} (elapsed={elapsed:.1f}s)")
            break

        candidate = polish_mutate(best_cfg, rng, args.p_replace)
        cand_key = iterate._config_signature(candidate)
        retries = 0
        while cand_key in tried and retries < 10:
            candidate = polish_mutate(best_cfg, rng, args.p_replace)
            cand_key = iterate._config_signature(candidate)
            retries += 1
        if cand_key in tried:
            continue
        tried.add(cand_key)

        iterate.write_config(candidate)
        score = iterate.evaluate(args.eval_maps, "factory_plan", "results")
        delta = score - best_score
        accept = score > best_score
        if accept:
            best_score = score
            best_cfg = candidate
            accepts += 1
        else:
            iterate.write_config(best_cfg)

        # determine source label
        src = "replace" if rng.random() < 0  else "tweak"  # noop — we forgot to record
        # Re-derive by comparing candidate to best_cfg structure
        src = "polish"

        log_fh.write(
            json.dumps({
                "ts": iterate._now_iso(),
                "iter": i,
                "score": score,
                "accept": accept,
                "best": best_score,
                "delta": delta,
                "elapsed_sec": round(elapsed, 2),
            }) + "\n"
        )
        log_fh.flush()
        print(f"{i:>4}  {src:<8}  {delta:>+7.3f}  {score:>7.2f}  {best_score:>7.2f}  "
              f"{('YES' if accept else 'no'):<4}")

    iterate.write_config(best_cfg)
    print(f"\nPolish done. {accepts} accepts in {time.time()-start:.1f}s")
    print(f"Final bench: {best_score:.3f}")

    log_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
