#!/usr/bin/env python3
"""Anti-SOTA tournament — propose seeds that AVOID current SOTA strategies.

N.1's ceiling analysis showed the 108-candidate pool is 98% saturated.
To push SOTA past 49.79 we need GENUINELY NEW candidates, not lottery
seeds. This script:

  1) Reads the current SOTA portfolio (12 strategies in factory_plan.py).
  2) Asks the LLM (gpt-5.5 xhigh) for 4 starting portfolios that are
     EXPLICITLY DISJOINT from the SOTA — different lane_y_set, different
     resource_pattern, different miner_pick where possible. The prompt
     lists the SOTA's strategies and says "do not propose anything like
     these".
  3) Spawns 4 parallel iterate.py workers from those anti-SOTA seeds.
  4) Saves the merged result as a new candidate pool to feed N.3's
     greedy submodular re-run.

Usage:
    python tournament_anti_sota.py
    python tournament_anti_sota.py --seed-base 800
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import iterate  # noqa: E402
import iterate_llm  # noqa: E402


ANTI_SOTA_PROMPT_TEMPLATE = """You are seeding a factory-layout autoresearch tournament that already
has a strong baseline. Your job is to propose ORTHOGONAL portfolios —
strategies that are GENUINELY DIFFERENT from the current state-of-the-art,
so the autoresearch loop can explore regions of config space that the
existing SOTA has NOT covered.

Each strategy is a dict with these 6 keys (every value from the listed enum):

  lane_y_set:        {lane_y_sets}
  asm_x_pattern:     {asm_x_patterns}
  smelter_offset:    {smelter_offsets}
  miner_pick:        {miner_picks}
  max_route_dist:    {max_route_values}   (null is allowed)
  resource_pattern:  {resource_patterns}

The CURRENT SOTA portfolio (50-map bench = {sota_score:.2f}) is:

{sota_strategies}

These strategies span lane_y_set values: {sota_lanes}
... resource_patterns: {sota_resources}
... miner_picks: {sota_miners}

PROPOSE EXACTLY {n_workers} starting portfolios that AVOID the lane_y_set
values and resource_patterns that the SOTA already heavily uses. Bias
toward:
  - lane_y_set values NOT in the SOTA's set: {missing_lanes}
  - resource_pattern values NOT well-represented in SOTA: {missing_resources}
  - miner_pick variations that look different from {sota_miners}
  - portfolio sizes 2-4 (cap=5, min=1).

Each portfolio should still be internally diverse (mix lane structures
across its 2-4 strategies). Don't just permute one starting strategy.

Return ONLY a JSON object with this shape, no markdown fences:
{{"portfolios": [
  {{"strategies": [{{"lane_y_set": "...", "asm_x_pattern": "...", "smelter_offset": 3, "miner_pick": "...", "max_route_dist": null, "resource_pattern": "..."}}, ...]}},
  ...  ({n_workers} portfolios total)
]}}
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget-sec", type=float, default=90.0)
    ap.add_argument("--eval-maps", type=int, default=30)
    ap.add_argument("--bench-maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=800)
    ap.add_argument("--model", default="gpt-5.5")
    ap.add_argument("--relay", default="86gs", choices=("crs", "86gs"))
    ap.add_argument("--meta-cap", type=int, default=12)
    return ap.parse_args()


def _call_llm_for_anti_sota_seeds(
    n: int, sota_cfg: dict, sota_score: float, model: str, relay: str,
) -> tuple[list[dict], float, str]:
    """Build the anti-SOTA prompt, return (portfolios, latency, raw_response)."""
    sota_lanes = sorted(set(s["lane_y_set"] for s in sota_cfg["strategies"]))
    sota_resources = sorted(set(s["resource_pattern"] for s in sota_cfg["strategies"]))
    sota_miners = sorted(set(s["miner_pick"] for s in sota_cfg["strategies"]))
    missing_lanes = [
        v for v in iterate.SEARCH_SPACE["lane_y_set"]
        if v not in sota_lanes
    ]
    missing_resources = [
        v for v in iterate.SEARCH_SPACE["resource_pattern"]
        if v not in sota_resources
    ]
    sota_dump = "\n".join(
        f"  - {s['lane_y_set']}/{s['asm_x_pattern']}/{s['smelter_offset']}/"
        f"{s['miner_pick']}/{s['max_route_dist']}/{s['resource_pattern']}"
        for s in sota_cfg["strategies"]
    )

    prompt = ANTI_SOTA_PROMPT_TEMPLATE.format(
        lane_y_sets=iterate.SEARCH_SPACE["lane_y_set"],
        asm_x_patterns=iterate.SEARCH_SPACE["asm_x_pattern"],
        smelter_offsets=iterate.SEARCH_SPACE["smelter_offset"],
        miner_picks=iterate.SEARCH_SPACE["miner_pick"],
        max_route_values=iterate.SEARCH_SPACE["max_route_dist"],
        resource_patterns=iterate.SEARCH_SPACE["resource_pattern"],
        sota_score=sota_score,
        sota_strategies=sota_dump,
        sota_lanes=sota_lanes,
        sota_resources=sota_resources,
        sota_miners=sota_miners,
        missing_lanes=missing_lanes,
        missing_resources=missing_resources,
        n_workers=n,
    )

    t0 = time.time()
    raw = iterate_llm.call_llm(prompt, model, relay, timeout_sec=120.0)
    latency = time.time() - t0

    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.MULTILINE).strip()
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

    # backfill with random "missing" strategies if needed
    import random as _random
    rng = _random.Random(42)
    while len(portfolios) < n:
        k = rng.randint(2, 3)
        portfolios.append({
            "strategies": [iterate._random_strategy(rng) for _ in range(k)]
        })

    return portfolios[:n], latency, raw


def main() -> int:
    args = parse_args()
    workers_dir = HERE / "results" / "_workers_anti_sota"
    workers_dir.mkdir(parents=True, exist_ok=True)

    sota_cfg = iterate.read_config()
    print(f"  current SOTA portfolio has {len(sota_cfg['strategies'])} strategies")
    sota_score = iterate.evaluate(args.bench_maps, "factory_plan", "results")
    print(f"  baseline 50-map bench: {sota_score:.3f}")

    print(f"\n  asking {args.model} (relay={args.relay}) for {args.workers} anti-SOTA portfolios…")
    portfolios, latency, raw = _call_llm_for_anti_sota_seeds(
        args.workers, sota_cfg, sota_score, args.model, args.relay,
    )
    print(f"  LLM responded in {latency:.1f}s with {len(portfolios)} portfolios:")
    for i, p in enumerate(portfolios):
        sig = " ; ".join(
            f"{s['lane_y_set']}/{s['asm_x_pattern']}/{s['smelter_offset']}"
            f"/{s['miner_pick']}/{s['max_route_dist']}/{s['resource_pattern']}"
            for s in p["strategies"]
        )
        print(f"    worker {i}  [{len(p['strategies'])}]  {sig}")

    procs = []
    for i, portfolio in enumerate(portfolios):
        wdir = workers_dir / f"w{i}"
        wdir.mkdir(parents=True, exist_ok=True)
        target = HERE / f"factory_plan_llm_w{i}.py"
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
        print(f"  spawned worker {i}  pid={p.pid}")

    print(f"\nWaiting for {args.workers} workers ({args.budget_sec}s each, parallel)…")
    start = time.time()
    for w in procs:
        rc = w["proc"].wait()
        w["stdout"].close()
        print(f"  worker {w['i']:>2} done in {time.time()-start:>5.1f}s (rc={rc})")

    # collect strategies
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
            f"  worker {w['i']:>2}  end[{len(cfg['strategies'])}]  final={final_score:.3f}"
        )

    summary = {
        "workers": args.workers,
        "budget_sec": args.budget_sec,
        "eval_maps": args.eval_maps,
        "model": args.model,
        "relay": args.relay,
        "sota_baseline_score": sota_score,
        "llm_latency_sec": round(latency, 2),
        "elapsed_sec": round(time.time() - start + latency, 1),
        "worker_results": worker_results,
        "merged_strategies": all_strategies,  # raw union; greedy_submodular will dedup+rank
    }
    out = HERE / "results" / "tournament_anti_sota.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\n  summary -> {out}")

    # restore SOTA factory_plan.py (anti-sota run doesn't update SOTA)
    iterate.write_config(sota_cfg)
    print(f"  factory_plan.py restored to SOTA portfolio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
