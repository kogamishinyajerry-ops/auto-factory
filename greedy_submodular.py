#!/usr/bin/env python3
"""Greedy submodular selection of best mixture-of-experts portfolio.

Champion-of-Champions failed because "top-12 by individual score" picked
12 strategies that all looked alike (mostly y_dense). MoE needs DIVERSE
experts so that the per-map best-of always has a good option.

This script does greedy SUBMODULAR selection:
  - Score all candidate strategies on all bench maps (matrix of
    strategy × map → score, computed once).
  - At each step, add the candidate strategy that maximises the sum of
    per-map best scores (i.e., the marginal "lift" of new map-wins).
  - Stop when portfolio size = K or marginal lift ≤ 0.

This is the canonical maximum-coverage / max-k-cover greedy that
guarantees (1-1/e)≈0.63 of optimum for monotone submodular objectives.

Usage:
    python greedy_submodular.py
    python greedy_submodular.py --k 12 --bench-maps 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import iterate  # noqa: E402
import factory_plan  # noqa: E402
from auto_factory import build_from_spec, generate_map, score_plan, simulate  # noqa: E402


SOURCE_RUNS = [
    "results/tournament_gpt55_xhigh.json",
    "results/tournament_gpt55_xhigh_rep2.json",
    "results/tournament_gpt54_seed400.json",
    "results/tournament_gpt54_seed600.json",
    "results/tournament_llm_seeded_6w.json",
    "results/tournament_llm_seeded.json",
    "results/tournament_anti_sota.json",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=12,
                    help="target portfolio size")
    ap.add_argument("--bench-maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--out-json", default="results/greedy_submodular.json")
    return ap.parse_args()


def _signature(s: dict) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in s.items()))


def main() -> int:
    args = parse_args()

    # collect candidates
    all_strategies = []
    for f in SOURCE_RUNS:
        p = HERE / f
        if not p.exists():
            continue
        j = json.loads(p.read_text())
        for w in j.get("worker_results", []):
            for s in w.get("strategies", []):
                all_strategies.append(s)
        for s in j.get("merged_strategies", []):
            all_strategies.append(s)

    seen: set[tuple] = set()
    candidates: list[dict] = []
    for s in all_strategies:
        key = _signature(s)
        if key not in seen:
            seen.add(key)
            candidates.append(s)
    print(f"  {len(candidates)} unique candidate strategies")
    print(f"  building {len(candidates)} × {args.bench_maps} score matrix…")

    # build score matrix: rows = strategies, cols = maps
    score_matrix: list[list[float]] = []
    for ci, s in enumerate(candidates):
        spec = factory_plan._expand_strategy(s)
        row = []
        for m in range(args.bench_maps):
            gmap = generate_map(seed=args.seed_base + m)
            try:
                plan = build_from_spec(gmap, spec)
                sim = simulate(plan, gmap, ticks=600)
                row.append(score_plan(sim).total)
            except Exception:
                row.append(float("-inf"))
        score_matrix.append(row)
        if (ci + 1) % 20 == 0 or ci == len(candidates) - 1:
            print(f"    [{ci + 1:>3}/{len(candidates)}]")

    # greedy submodular
    print(f"\n  running greedy max-k-cover, k={args.k}…")
    selected: list[int] = []
    best_per_map = [float("-inf")] * args.bench_maps
    history = []
    for step in range(args.k):
        # pick the candidate that maximises sum-of-(new per-map best)
        best_lift = -1.0
        best_idx = -1
        for ci in range(len(candidates)):
            if ci in selected:
                continue
            lift = 0.0
            for m in range(args.bench_maps):
                lift += max(score_matrix[ci][m], best_per_map[m]) - max(0.0, best_per_map[m] if best_per_map[m] != float("-inf") else 0.0)
            if lift > best_lift:
                best_lift = lift
                best_idx = ci
        if best_idx < 0:
            break
        selected.append(best_idx)
        # update best_per_map
        new_total = 0.0
        for m in range(args.bench_maps):
            best_per_map[m] = max(score_matrix[best_idx][m], best_per_map[m])
            new_total += best_per_map[m]
        cumulative = new_total / args.bench_maps
        history.append({
            "step": step + 1,
            "picked": candidates[best_idx],
            "marginal_lift": round(best_lift, 3),
            "cumulative_50map_bench": round(cumulative, 3),
        })
        print(
            f"    pick #{step + 1:>2}  lift {best_lift:>6.2f}  "
            f"cumulative {cumulative:.3f}   "
            f"{candidates[best_idx]['lane_y_set']}/"
            f"{candidates[best_idx]['asm_x_pattern']}/"
            f"{candidates[best_idx]['smelter_offset']}/"
            f"{candidates[best_idx]['miner_pick']}/"
            f"{candidates[best_idx]['max_route_dist']}/"
            f"{candidates[best_idx]['resource_pattern']}"
        )

    # final portfolio + real bench
    portfolio = {"strategies": [candidates[i] for i in selected]}
    iterate.write_config(portfolio)
    real_bench = iterate.evaluate(args.bench_maps, "factory_plan", "results")
    print(f"\n  greedy-submodular portfolio ({args.k}-strategy) bench: {real_bench:.3f}")

    # the greedy oracle says...
    oracle_score = sum(best_per_map) / args.bench_maps
    print(f"  oracle (per-map argmax across selected): {oracle_score:.3f}")
    print(f"  delta (oracle - real): {oracle_score - real_bench:+.3f}   "
          f"(zero would mean MoE picks oracle every map)")

    out = {
        "k": args.k,
        "bench_maps": args.bench_maps,
        "n_candidates": len(candidates),
        "history": history,
        "selected_portfolio": portfolio,
        "oracle_score": oracle_score,
        "real_bench": real_bench,
    }
    out_path = HERE / args.out_json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\n  summary -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
