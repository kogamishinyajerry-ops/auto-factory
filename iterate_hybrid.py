#!/usr/bin/env python3
"""Hybrid LLM + random mutation loop (Phase I).

Phase H showed LLM is sample-efficient (42% accept) but ~350x slower per
attempt than random. This module tries to keep the best of both:

  - **LLM acts as a META-controller**: every K iterations it proposes a
    fresh starting portfolio (a "basin"). It sees the history of past
    basins — what we started from, what we converged to, accept counts —
    and can suggest a totally different region of config space.
  - **Random does the inner hill-climb**: K cheap mutations per basin,
    greedy-accept. Random handles "tactics" — single-key tweaks that
    are too cheap to waste an LLM call on.

Budget shape (600s default):
  - 10 basins × 20 inner iters × ~150 ms each ≈ 30s of random work
  - 10 LLM calls × ~50s each                   ≈ 500s of LLM work
  Total ≈ 530s, leaves headroom for variance.

If LLM call fails / parses to garbage / proposes a duplicate basin we've
already explored, we fall back to a random restart so the loop never
stalls.

Usage:
    python iterate_hybrid.py
    python iterate_hybrid.py --basins 8 --inner-iters 25
    python iterate_hybrid.py --reset --eval-maps 30
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
import iterate_llm  # noqa: E402


META_PROMPT_TEMPLATE = """You are a meta-controller guiding a factory-layout search.

The planner runs a PORTFOLIO of strategies on each map and keeps whichever
scores highest per map (Mixture-of-Experts). Each strategy is a dict with
these 6 keys; every value MUST come from the listed enum:

  lane_y_set:        {lane_y_sets}
  asm_x_pattern:     {asm_x_patterns}
  smelter_offset:    {smelter_offsets}
  miner_pick:        {miner_picks}
  max_route_dist:    {max_route_values}   (null is allowed; means no filter)
  resource_pattern:  {resource_patterns}

Score per map = widgets_per_minute + 3.0 * distinct_plate_types_used
              - belt_crossing_penalty - building_cost * 0.05
              - energy * 0.0005 - congestion * 0.001
Higher = better. Bench is averaged over 50 deterministic maps.

We have already explored {n_basins} "basins". A basin = a starting portfolio
+ {inner_iters} random hill-climb iterations that try single-key tweaks /
swaps / add / remove. Here's what we found:

{basin_history}

Overall best score so far: {global_best:.3f}

Your job is to propose a NEW starting portfolio for the next basin. The
goal is DIVERSITY — pick a region of config space we haven't explored
well. Don't propose anything that's just a small tweak of a basin we've
already visited; the random hill-climb will do that itself. Bias toward
2-4 strategies in the portfolio (cap = 5, min = 1).

Return ONLY a JSON object with this shape, no markdown fences:
{{"strategies": [{{"lane_y_set": "...", "asm_x_pattern": "...", "smelter_offset": 3, "miner_pick": "...", "max_route_dist": null, "resource_pattern": "..."}}, ...]}}
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basins", type=int, default=10,
                    help="number of LLM-proposed basin restarts")
    ap.add_argument("--inner-iters", type=int, default=20,
                    help="random hill-climb iterations per basin")
    ap.add_argument("--eval-maps", type=int, default=20)
    ap.add_argument("--bench-maps", type=int, default=50)
    ap.add_argument("--budget-sec", type=float, default=600.0)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--model", default="gpt-5.4")
    ap.add_argument("--relay", default="crs", choices=("crs", "86gs"))
    ap.add_argument("--log-file", default="results/iterate_hybrid.jsonl")
    ap.add_argument("--seed", type=int, default=42)
    return ap.parse_args()


def _render_basin_history(basins: list[dict]) -> str:
    if not basins:
        return "  (none yet — this is the first basin)"
    lines = []
    for b in basins:
        sig = "; ".join(
            f"{s['lane_y_set']}/{s['asm_x_pattern']}/{s['smelter_offset']}/"
            f"{s['miner_pick']}/{s['max_route_dist']}/{s['resource_pattern']}"
            for s in b["start_cfg"]["strategies"]
        )
        lines.append(
            f"  basin {b['basin']}: started from [{len(b['start_cfg']['strategies'])}] {sig}"
        )
        lines.append(
            f"    → converged to score {b['basin_best_score']:.2f} "
            f"({b['n_accepts']} accepts / {b['n_attempts']} attempts)"
        )
    return "\n".join(lines)


def _propose_basin_via_llm(
    basins: list[dict],
    global_best: float,
    inner_iters: int,
    model: str,
    relay: str,
    rng: random.Random,
) -> tuple[dict, str, float]:
    """Return (next_starting_cfg, source_tag, llm_latency_sec)."""
    prompt = META_PROMPT_TEMPLATE.format(
        lane_y_sets=iterate.SEARCH_SPACE["lane_y_set"],
        asm_x_patterns=iterate.SEARCH_SPACE["asm_x_pattern"],
        smelter_offsets=iterate.SEARCH_SPACE["smelter_offset"],
        miner_picks=iterate.SEARCH_SPACE["miner_pick"],
        max_route_values=iterate.SEARCH_SPACE["max_route_dist"],
        resource_patterns=iterate.SEARCH_SPACE["resource_pattern"],
        n_basins=len(basins),
        basin_history=_render_basin_history(basins),
        global_best=global_best,
        inner_iters=inner_iters,
    )
    t0 = time.time()
    raw = iterate_llm.call_llm(prompt, model, relay)
    latency = time.time() - t0

    candidate = iterate_llm.parse_config(raw) if raw else None
    if candidate is None or not iterate_llm.validate_config(candidate):
        # fall back to a random portfolio of 2-3 strategies
        n = rng.randint(2, 3)
        candidate = {"strategies": [iterate._random_strategy(rng) for _ in range(n)]}
        return candidate, "fallback_random_restart", latency
    return candidate, "llm_meta", latency


def _inner_basin(
    start_cfg: dict,
    eval_maps: int,
    inner_iters: int,
    rng: random.Random,
    tried: set[tuple],
    log_fh,
    basin_idx: int,
    start_iter_counter: int,
) -> tuple[dict, float, int, int, int]:
    """Run random hill-climb from start_cfg. Returns
    (basin_best_cfg, basin_best_score, n_accepts, n_attempts, end_iter_counter).
    """
    iterate.write_config(start_cfg)
    cur_score = iterate.evaluate(eval_maps, "factory_plan", "results")
    cur_cfg = start_cfg
    basin_best_cfg = start_cfg
    basin_best_score = cur_score
    n_accepts = 0
    n_attempts = 0
    iter_counter = start_iter_counter

    # log the basin's starting evaluation
    iter_counter += 1
    log_fh.write(
        json.dumps(
            {
                "ts": iterate._now_iso(),
                "iter": iter_counter,
                "basin": basin_idx,
                "cfg": cur_cfg,
                "score": cur_score,
                "accept": True,
                "best_in_basin": cur_score,
                "source": "basin_start",
            }
        )
        + "\n"
    )
    log_fh.flush()

    for _ in range(inner_iters):
        candidate = iterate.mutate(cur_cfg, rng)
        cand_key = iterate._config_signature(candidate)
        retries = 0
        while cand_key in tried and retries < 10:
            candidate = iterate.mutate(cur_cfg, rng)
            cand_key = iterate._config_signature(candidate)
            retries += 1
        if cand_key in tried:
            continue
        tried.add(cand_key)

        iterate.write_config(candidate)
        score = iterate.evaluate(eval_maps, "factory_plan", "results")
        n_attempts += 1
        iter_counter += 1
        accept = score > cur_score
        if accept:
            cur_cfg = candidate
            cur_score = score
            n_accepts += 1
            if score > basin_best_score:
                basin_best_cfg = candidate
                basin_best_score = score
        else:
            iterate.write_config(cur_cfg)  # revert in-file state

        log_fh.write(
            json.dumps(
                {
                    "ts": iterate._now_iso(),
                    "iter": iter_counter,
                    "basin": basin_idx,
                    "cfg": candidate,
                    "score": score,
                    "accept": accept,
                    "best_in_basin": basin_best_score,
                    "source": "inner_random",
                }
            )
            + "\n"
        )
        log_fh.flush()

    return basin_best_cfg, basin_best_score, n_accepts, n_attempts, iter_counter


def main() -> int:
    args = parse_args()
    log_path = HERE / args.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a")
    rng = random.Random(args.seed)

    if args.reset:
        start = dict(iterate.RESET_CONFIG)
        iterate.write_config(start)
    else:
        start = iterate.read_config()

    print(
        f"HYBRID AutoResearch — basins={args.basins} inner_iters={args.inner_iters} "
        f"eval_maps={args.eval_maps} relay={args.relay} model={args.model}"
    )
    print(f"Initial CONFIG: {len(start['strategies'])} strategies")

    # log a session header so the JSONL is self-describing across reruns
    log_fh.write(
        json.dumps(
            {
                "ts": iterate._now_iso(),
                "iter": -2,
                "kind": "session_start",
                "basins": args.basins,
                "inner_iters": args.inner_iters,
                "eval_maps": args.eval_maps,
            }
        )
        + "\n"
    )
    log_fh.flush()

    tried: set[tuple] = set()
    basins: list[dict] = []  # history fed to LLM
    global_best_cfg = start
    global_best_score = float("-inf")
    iter_counter = 0
    t_start = time.time()

    print(f"{'basin':>5}  {'src':<10}  {'best/basin':>10}  {'best/global':>11}  "
          f"{'accepts':>7}  {'inner_t':>7}  {'llm_t':>6}")
    print("-" * 78)

    for b in range(1, args.basins + 1):
        elapsed = time.time() - t_start
        if elapsed > args.budget_sec:
            print(f"\nbudget exhausted at basin {b - 1} (elapsed={elapsed:.1f}s)")
            break

        # propose next basin start
        if b == 1:
            next_start = start
            source = "initial"
            llm_latency = 0.0
        else:
            next_start, source, llm_latency = _propose_basin_via_llm(
                basins, global_best_score, args.inner_iters, args.model,
                args.relay, rng,
            )
            # dedup: don't re-explore a basin we've seen
            sig = iterate._config_signature(next_start)
            if sig in {iterate._config_signature(prev["start_cfg"]) for prev in basins}:
                # nudge it
                next_start = iterate.mutate(next_start, rng)
                source = source + "+nudge"

        # log the basin proposal
        log_fh.write(
            json.dumps(
                {
                    "ts": iterate._now_iso(),
                    "iter": iter_counter,
                    "basin": b,
                    "kind": "basin_proposal",
                    "start_cfg": next_start,
                    "source": source,
                    "llm_latency_sec": round(llm_latency, 2),
                }
            )
            + "\n"
        )
        log_fh.flush()

        inner_t0 = time.time()
        basin_best_cfg, basin_best_score, n_acc, n_att, iter_counter = _inner_basin(
            next_start, args.eval_maps, args.inner_iters, rng,
            tried, log_fh, b, iter_counter,
        )
        inner_dt = time.time() - inner_t0

        # update global best
        if basin_best_score > global_best_score:
            global_best_cfg = basin_best_cfg
            global_best_score = basin_best_score

        basins.append({
            "basin": b,
            "start_cfg": next_start,
            "basin_best_cfg": basin_best_cfg,
            "basin_best_score": basin_best_score,
            "n_accepts": n_acc,
            "n_attempts": n_att,
            "source": source,
        })

        print(
            f"{b:>5}  {source[:10]:<10}  {basin_best_score:>10.2f}  "
            f"{global_best_score:>11.2f}  {n_acc}/{n_att:<5}  "
            f"{inner_dt:>6.1f}s  {llm_latency:>5.1f}s"
        )

    # write best back to file
    iterate.write_config(global_best_cfg)
    print(f"\nDone. Global best ({len(global_best_cfg['strategies'])} strategies): "
          f"{global_best_score:.3f}")
    print(f"\nFinal {args.bench_maps}-map bench of best CONFIG…")
    final = iterate.evaluate(args.bench_maps, "factory_plan", "results")
    print(f"  factory_plan ({args.bench_maps} maps) mean: {final:.3f}")

    log_fh.write(
        json.dumps(
            {
                "ts": iterate._now_iso(),
                "iter": -1,
                "kind": "final",
                "cfg": global_best_cfg,
                "bench_maps": args.bench_maps,
                "bench_score": final,
                "n_basins": len(basins),
                "elapsed_sec": round(time.time() - t_start, 2),
            }
        )
        + "\n"
    )
    log_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
