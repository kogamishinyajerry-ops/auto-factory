#!/usr/bin/env python3
"""LLM-seeded parallel tournament (Phase J).

Synthesis of Phase G (parallel random workers + diversity merge) and
Phase I (LLM as meta-controller proposing diverse starts):

  1. ONE LLM call asks gpt-5.4 for K diverse starting portfolios.
  2. Spawn K parallel `iterate.py` workers, each starting from one of
     those portfolios. They each do random hill-climb in parallel.
  3. After all workers finish, union their best portfolios + diversity-
     merge (same logic as tournament.py).

Why this might beat both Phase G and Phase I:
  - vs Phase G: LLM injects diversity at seed time, so the K workers
    start from K genuinely different regions (not just K random seeds).
  - vs Phase I: parallelism — K workers do work simultaneously instead
    of sequentially exploring basins.

LLM cost is bounded to ONE call (~50-90s); the rest of the budget goes
to parallel hill-climbing.

Usage:
    python tournament_llm_seeded.py
    python tournament_llm_seeded.py --workers 4 --budget-sec 90 --eval-maps 30
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
sys.path.insert(0, str(HERE))

import iterate  # noqa: E402
import iterate_llm  # noqa: E402


SEED_PROMPT_TEMPLATE = """You are seeding a factory-layout autoresearch tournament.

The planner runs a PORTFOLIO of strategies (Mixture-of-Experts) per map
and keeps the highest-scoring per map. Each strategy is a dict with these
6 keys; every value MUST come from the listed enum:

  lane_y_set:        {lane_y_sets}
  asm_x_pattern:     {asm_x_patterns}
  smelter_offset:    {smelter_offsets}
  miner_pick:        {miner_picks}
  max_route_dist:    {max_route_values}   (null is allowed; means no filter)
  resource_pattern:  {resource_patterns}

Score per map = widgets_per_minute + 3.0 * distinct_plate_types_used
              - belt_crossing_penalty - building_cost * 0.05
              - energy * 0.0005 - congestion * 0.001
Bench is averaged over 50 deterministic maps.

We will spawn {n_workers} parallel hill-climbers, each starting from one
of YOUR proposed portfolios and doing random single-key mutations.

Your job: propose EXACTLY {n_workers} distinct starting portfolios. They
should explore DIFFERENT regions of config space — different lane_y_set
choices, different resource_patterns, varied portfolio sizes. Don't just
permute the same portfolio in tiny ways; we want the workers to be
genuinely searching different regions in parallel.

Each portfolio should be 1-5 strategies (cap = 5). Bias toward 2-4
strategies; a 1-strategy portfolio is fine for one "minimalist" worker.

Return ONLY a JSON object with this shape, no markdown fences:
{{"portfolios": [
  {{"strategies": [{{"lane_y_set": "...", "asm_x_pattern": "...", "smelter_offset": 3, "miner_pick": "...", "max_route_dist": null, "resource_pattern": "..."}}, ...]}},
  {{"strategies": [...]}}
  ...  ({n_workers} portfolios total)
]}}
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget-sec", type=float, default=90.0,
                    help="per-worker wall-clock budget")
    ap.add_argument("--eval-maps", type=int, default=30)
    ap.add_argument("--bench-maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=200)
    ap.add_argument("--model", default="gpt-5.4")
    ap.add_argument("--relay", default="crs", choices=("crs", "86gs"))
    ap.add_argument("--meta-cap", type=int, default=12)
    ap.add_argument("--no-merge", action="store_true")
    return ap.parse_args()


def _call_llm_for_seeds(n: int, model: str, relay: str) -> tuple[list[dict], float]:
    """Return (list-of-portfolios, llm_latency_sec). Falls back to random
    portfolios if parse/validate fails."""
    prompt = SEED_PROMPT_TEMPLATE.format(
        lane_y_sets=iterate.SEARCH_SPACE["lane_y_set"],
        asm_x_patterns=iterate.SEARCH_SPACE["asm_x_pattern"],
        smelter_offsets=iterate.SEARCH_SPACE["smelter_offset"],
        miner_picks=iterate.SEARCH_SPACE["miner_pick"],
        max_route_values=iterate.SEARCH_SPACE["max_route_dist"],
        resource_patterns=iterate.SEARCH_SPACE["resource_pattern"],
        n_workers=n,
    )
    t0 = time.time()
    raw = iterate_llm.call_llm(prompt, model, relay, timeout_sec=120.0)
    latency = time.time() - t0

    # custom parse: expects {"portfolios": [{"strategies": [...]}, ...]}
    import re as _re
    cleaned = _re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=_re.MULTILINE).strip()
    # find the largest balanced {...}
    candidate = None
    start = cleaned.find("{")
    if start >= 0:
        depth = 0
        for i, c in enumerate(cleaned[start:], start=start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start : i + 1]
                    break
    try:
        obj = json.loads(candidate) if candidate else None
    except json.JSONDecodeError:
        obj = None

    portfolios: list[dict] = []
    if isinstance(obj, dict) and isinstance(obj.get("portfolios"), list):
        for p in obj["portfolios"]:
            if iterate_llm.validate_config(p):
                portfolios.append(p)

    # backfill with random if LLM under-delivered
    import random as _random
    rng = _random.Random(42)
    while len(portfolios) < n:
        k = rng.randint(2, 3)
        portfolios.append({
            "strategies": [iterate._random_strategy(rng) for _ in range(k)]
        })

    return portfolios[:n], latency


def _portfolio_summary(p: dict) -> str:
    return " ; ".join(
        f"{s['lane_y_set'][2:]}/{s['asm_x_pattern']}/{s['smelter_offset']}"
        f"/{s['miner_pick']}/{s['max_route_dist']}/{s['resource_pattern']}"
        for s in p["strategies"]
    )


def main() -> int:
    args = parse_args()
    workers_dir = HERE / "results" / "_workers_llm_seeded"
    workers_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"LLM-seeded tournament — workers={args.workers} budget={args.budget_sec}s "
        f"eval_maps={args.eval_maps} relay={args.relay} model={args.model}"
    )
    print(f"  → asking LLM for {args.workers} diverse starting portfolios…")
    portfolios, llm_latency = _call_llm_for_seeds(args.workers, args.model, args.relay)
    print(f"  LLM responded in {llm_latency:.1f}s with {len(portfolios)} portfolios:")
    for i, p in enumerate(portfolios):
        print(f"    worker {i}  [{len(p['strategies'])}]  {_portfolio_summary(p)}")

    procs = []
    for i, portfolio in enumerate(portfolios):
        wdir = workers_dir / f"w{i}"
        wdir.mkdir(parents=True, exist_ok=True)
        target = HERE / f"factory_plan_llm_w{i}.py"
        # bootstrap target file from factory_plan.py shell, then overwrite CONFIG
        shutil.copy(HERE / "factory_plan.py", target)
        iterate.write_config(portfolio, path=target)
        log_path = wdir / "iterate.jsonl"
        log_path.unlink(missing_ok=True)

        cmd = [
            sys.executable,
            str(HERE / "iterate.py"),
            "--budget-sec", str(args.budget_sec),
            "--eval-maps", str(args.eval_maps),
            "--bench-maps", str(args.bench_maps),
            "--seed", str(args.seed_base + i),
            # NB: NO --reset, we want the LLM-seeded portfolio to be the start
            "--target-file", str(target),
            "--planner-name", target.stem,
            "--log-file", str(log_path),
            "--eval-out-dir", str(wdir),
            "--quiet",
        ]
        stdout_log = (wdir / "stdout.log").open("w")
        p = subprocess.Popen(cmd, stdout=stdout_log, stderr=subprocess.STDOUT, cwd=HERE)
        procs.append({
            "i": i, "proc": p, "target": target, "wdir": wdir,
            "stdout": stdout_log, "seed_portfolio": portfolio,
        })
        print(f"  spawned worker {i}  pid={p.pid}  seed={args.seed_base + i}")

    print(f"\nWaiting for {args.workers} workers ({args.budget_sec}s each, parallel)…")
    start = time.time()
    for w in procs:
        rc = w["proc"].wait()
        w["stdout"].close()
        print(f"  worker {w['i']:>2} done in {time.time() - start:>5.1f}s (rc={rc})")

    worker_results = []
    all_strategies: list[dict] = []
    for w in procs:
        cfg = iterate.read_config(w["target"])
        text = (w["wdir"] / "stdout.log").read_text()
        final_line = next(
            (ln for ln in text.splitlines()
             if "(50 maps) mean" in ln or "(maps) mean" in ln),
            "",
        )
        try:
            final_score = float(final_line.split("mean:")[-1].strip())
        except (ValueError, IndexError):
            final_score = float("nan")
        worker_results.append({
            "worker": w["i"],
            "score": final_score,
            "n_strategies": len(cfg["strategies"]),
            "strategies": cfg["strategies"],
            "seed_portfolio": w["seed_portfolio"],
        })
        for s in cfg["strategies"]:
            all_strategies.append(s)
        print(
            f"  worker {w['i']:>2}  start[{len(w['seed_portfolio']['strategies'])}] "
            f"→ end[{len(cfg['strategies'])}]  final={final_score:.3f}"
        )

    # dedup
    seen: set[tuple] = set()
    unique: list[dict] = []
    for s in all_strategies:
        key = tuple((k, repr(v)) for k, v in sorted(s.items()))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    print(f"\nMerged {len(all_strategies)} → {len(unique)} unique strategies")

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

    meta_cfg = {"strategies": unique}
    meta_score = float("nan")
    bench_score = float("nan")
    if not args.no_merge:
        iterate.write_config(meta_cfg, path=HERE / "factory_plan.py")
        print(f"\nMerged portfolio of {len(unique)} strategies written to factory_plan.py")
        print(f"Final {args.bench_maps}-map bench of merged portfolio…")
        bench_score = iterate.evaluate(args.bench_maps, "factory_plan", "results")
        print(f"  factory_plan ({args.bench_maps} maps) mean: {bench_score:.3f}")
        meta_score = bench_score

    summary = {
        "workers": args.workers,
        "budget_sec": args.budget_sec,
        "eval_maps": args.eval_maps,
        "bench_maps": args.bench_maps,
        "llm_seed_latency_sec": round(llm_latency, 2),
        "elapsed_sec": round(time.time() - start + llm_latency, 1),
        "worker_results": worker_results,
        "n_merged_strategies": len(unique),
        "merged_bench_score": bench_score,
        "merged_strategies": unique,
    }
    (workers_dir.parent / "tournament_llm_seeded.json").write_text(
        json.dumps(summary, indent=2)
    )
    print(f"\n  summary -> {workers_dir.parent / 'tournament_llm_seeded.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
