#!/usr/bin/env python3
"""Champion-of-Champions: meta-merge top strategies across ALL prior runs.

Collects every strategy from every tournament_*.json file (J's gpt-5.4,
L.1's gpt-5.5 xhigh, L.2-A, L.2-B, K's 6-worker), dedups, individually
benches each on N maps (single-strategy plan() is ~10ms/map → fast),
takes the top 12 by individual score, assembles into a portfolio, and
benches the portfolio on M maps to see if "best ideas across runs" beats
any single run's portfolio.

This is a free upgrade if successful: we already paid to discover these
strategies; we're just being smarter about which to keep.

Usage:
    python champion_of_champions.py
    python champion_of_champions.py --top 12 --bench-maps 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import iterate  # noqa: E402


SOURCE_RUNS = [
    "results/tournament_gpt55_xhigh.json",     # L.1 — gpt-5.5 xhigh SOTA 44.88
    "results/tournament_gpt54_seed400.json",   # L.2-A — gpt-5.4 43.05
    "results/tournament_gpt54_seed600.json",   # L.2-B — gpt-5.4 41.16
    "results/tournament_llm_seeded_6w.json",   # K   — gpt-5.4 6w 41.05
    "results/tournament_llm_seeded.json",      # current latest run
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--screen-maps", type=int, default=50,
                    help="maps used to score each candidate strategy individually")
    ap.add_argument("--bench-maps", type=int, default=50,
                    help="maps used for the final merged portfolio bench")
    ap.add_argument("--out-json", default="results/champion_of_champions.json")
    return ap.parse_args()


def _signature(s: dict) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in s.items()))


def main() -> int:
    args = parse_args()

    all_strategies = []
    sources_seen = []
    for f in SOURCE_RUNS:
        p = HERE / f
        if not p.exists():
            continue
        sources_seen.append(f)
        j = json.loads(p.read_text())
        for w in j.get("worker_results", []):
            for s in w.get("strategies", []):
                all_strategies.append((s, f))
        for s in j.get("merged_strategies", []):
            all_strategies.append((s, f))

    print(f"  read {len(sources_seen)} run files, {len(all_strategies)} total strategies")

    # dedup
    seen: set[tuple] = set()
    unique: list[tuple[dict, list[str]]] = []
    sig_to_idx = {}
    for s, src in all_strategies:
        key = _signature(s)
        if key not in seen:
            seen.add(key)
            sig_to_idx[key] = len(unique)
            unique.append((s, [src]))
        else:
            unique[sig_to_idx[key]][1].append(src)
    print(f"  {len(unique)} unique strategies after dedup")

    # bench each strategy individually
    print(f"  benching each on {args.screen_maps} maps…")
    scored: list[tuple[float, dict, list[str]]] = []
    for i, (s, srcs) in enumerate(unique):
        cfg = {"strategies": [s]}
        iterate.write_config(cfg)
        score = iterate.evaluate(args.screen_maps, "factory_plan", "results")
        scored.append((score, s, srcs))
        if (i + 1) % 10 == 0 or i == len(unique) - 1:
            print(f"    [{i + 1:>3}/{len(unique)}]  latest: {score:6.2f}")

    scored.sort(key=lambda t: -t[0])
    top = scored[: args.top]
    print(f"\n  top-{args.top} individual scores:")
    for rank, (sc, s, srcs) in enumerate(top, start=1):
        src_label = ", ".join(Path(x).stem.replace("tournament_", "") for x in srcs)
        print(
            f"    #{rank:>2}  {sc:6.2f}  "
            f"{s['lane_y_set']}/{s['asm_x_pattern']}/{s['smelter_offset']}/"
            f"{s['miner_pick']}/{s['max_route_dist']}/{s['resource_pattern']}"
            f"   (seen in: {src_label})"
        )

    # assemble + bench merged portfolio
    portfolio = {"strategies": [s for _sc, s, _srcs in top]}
    iterate.write_config(portfolio)
    merged_score = iterate.evaluate(args.bench_maps, "factory_plan", "results")
    print(f"\n  merged portfolio ({args.top}-strategy) {args.bench_maps}-map bench: "
          f"{merged_score:.3f}")

    out = {
        "sources": sources_seen,
        "n_unique_strategies": len(unique),
        "top": [
            {"rank": r + 1, "individual_score": sc, "strategy": s, "seen_in": srcs}
            for r, (sc, s, srcs) in enumerate(top)
        ],
        "merged_bench_score": merged_score,
        "merged_portfolio": portfolio,
    }
    out_path = HERE / args.out_json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\n  summary -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
