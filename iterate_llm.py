#!/usr/bin/env python3
"""LLM-driven mutation loop (Phase H).

Same outer shape as iterate.py — read CONFIG, propose a mutation, write,
evaluate, accept-if-better — but the mutation comes from a real LLM
(codex-crs / gpt-5.4 by default). Each turn we prompt the model with:

  - the current CONFIG
  - the current score
  - the last K accepted scores (so it sees the trajectory)
  - the search-space enum values

and ask it to return a fresh CONFIG (a one-step mutation, in JSON).

If the LLM call fails, the response can't be parsed, or the response
contains invalid enum values, we fall back to iterate.py's random
mutator so the loop never stalls.

Per-call cost is non-trivial (~5–10 s wall-clock, ~3–6 k tokens).
Default budget is 25 LLM calls + parallel cap so a 5-minute run lands.

Usage:
    python iterate_llm.py
    python iterate_llm.py --max-llm-calls 40 --eval-maps 50 --reset
    python iterate_llm.py --model gpt-5.5             # use 86gs xhigh
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
import iterate  # noqa: E402


PROMPT_TEMPLATE = """You are an autoresearch optimiser tuning a factory layout planner.

Each "strategy" in the portfolio is a dict with these 6 keys (every value
MUST come from the enum listed):

  lane_y_set:        {lane_y_sets}
  asm_x_pattern:     {asm_x_patterns}
  smelter_offset:    {smelter_offsets}
  miner_pick:        {miner_picks}
  max_route_dist:    {max_route_values}   (null is allowed; means no filter)
  resource_pattern:  {resource_patterns}

The planner runs ALL strategies on each map and keeps whichever scores
highest on that map (portfolio / MoE). Score per map =
    widgets_per_minute
    + 3.0 * distinct_plate_types_delivered_to_any_assembler   (max +12)
    - belt_crossing_penalty
    - building_cost * 0.05
    - energy * 0.0005
    - congestion * 0.001

Bench mean is averaged over 50 deterministic maps. Higher = better.

Current portfolio ({n_current} strategies):
{current_config}

Current mean score on the 50-map bench: {current_score:.3f}

Most recent attempts (newest last):
{history}

Propose ONE SMALL mutation of the portfolio that you predict will
improve the score. You can:
  - tweak one key of one existing strategy,
  - replace one existing strategy with a fresh one,
  - add a strategy (cap = 5),
  - or remove one (min = 1).

Bias toward small, targeted edits over wholesale rewrites — the loop
is already exploring random restarts on its own.

Return ONLY a JSON object with this shape, no markdown fences:
{{"strategies": [{{"lane_y_set": "...", "asm_x_pattern": "...", "smelter_offset": 3, "miner_pick": "...", "max_route_dist": null, "resource_pattern": "..."}}, ...]}}
"""


SEARCH_ENUM_REPR = {
    "lane_y_sets":      iterate.SEARCH_SPACE["lane_y_set"],
    "asm_x_patterns":   iterate.SEARCH_SPACE["asm_x_pattern"],
    "smelter_offsets":  iterate.SEARCH_SPACE["smelter_offset"],
    "miner_picks":      iterate.SEARCH_SPACE["miner_pick"],
    "max_route_values": iterate.SEARCH_SPACE["max_route_dist"],
    "resource_patterns": iterate.SEARCH_SPACE["resource_pattern"],
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-llm-calls", type=int, default=25)
    ap.add_argument("--eval-maps", type=int, default=50)
    ap.add_argument("--bench-maps", type=int, default=50)
    ap.add_argument("--budget-sec", type=float, default=600.0,
                    help="hard wall-clock cap")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument(
        "--model",
        default="gpt-5.4",
        help="codex model to drive the proposer (default gpt-5.4 via CRS)",
    )
    ap.add_argument(
        "--relay",
        default="crs",
        choices=("crs", "86gs"),
        help="which codex relay to use (default crs)",
    )
    ap.add_argument(
        "--log-file",
        default="results/iterate_llm.jsonl",
    )
    ap.add_argument("--seed", type=int, default=42, help="random fallback RNG")
    return ap.parse_args()


def call_llm(prompt: str, model: str, relay: str, timeout_sec: float = 90.0) -> str:
    """Run `codex exec` once and return the raw model response text."""
    codex_home = (
        Path.home() / ".codex-crs"
        if relay == "crs"
        else Path.home() / ".codex-relay"
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    cmd = ["codex", "exec", "--skip-git-repo-check"]
    if relay == "86gs":
        # 86gs relay needs explicit model override for non-default routing.
        cmd += ["-c", f'model="{model}"']
    cmd.append(prompt)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return ""
    if proc.returncode != 0:
        return ""
    # codex puts the model's reply on stdout (clean) and the transcript
    # / headers on stderr; we only want the reply.
    return proc.stdout.strip()


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_config(text: str) -> dict | None:
    """Extract a JSON CONFIG dict from the LLM's free-form response."""
    cleaned = _JSON_FENCE.sub("", text).strip()
    # try the whole thing first
    candidates = [cleaned]
    # also try the largest balanced {...} substring (in case prose leaks in)
    start = cleaned.find("{")
    if start >= 0:
        depth = 0
        for i, c in enumerate(cleaned[start:], start=start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(cleaned[start : i + 1])
                    break
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "strategies" in obj and isinstance(obj["strategies"], list):
            return obj
    return None


def validate_config(cfg: dict) -> bool:
    """Reject configs whose values fall outside the SEARCH_SPACE enums."""
    if not isinstance(cfg, dict):
        return False
    strategies = cfg.get("strategies")
    if not isinstance(strategies, list) or not strategies or len(strategies) > 5:
        return False
    for s in strategies:
        if not isinstance(s, dict):
            return False
        for key, allowed in iterate.SEARCH_SPACE.items():
            if key not in s:
                return False
            if s[key] not in allowed:
                return False
    return True


def render_history(history: list[dict]) -> str:
    if not history:
        return "  (none yet)"
    lines = []
    for h in history[-5:]:
        accepted = "ACCEPTED" if h["accept"] else "rejected"
        sig = "; ".join(
            f"{s['lane_y_set']}/{s['asm_x_pattern']}/{s['smelter_offset']}/"
            f"{s['miner_pick']}/{s['max_route_dist']}/{s['resource_pattern']}"
            for s in h["cfg"]["strategies"]
        )
        lines.append(f"  iter {h['iter']}: score {h['score']:.2f} ({accepted}) — [{len(h['cfg']['strategies'])}] {sig}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    log_path = HERE / args.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a")

    rng = random.Random(args.seed)

    if args.reset:
        best_cfg = dict(iterate.RESET_CONFIG)
        iterate.write_config(best_cfg)
    else:
        best_cfg = iterate.read_config()

    print(
        f"LLM AutoResearch — relay={args.relay} model={args.model}  "
        f"eval_maps={args.eval_maps}  max_llm_calls={args.max_llm_calls}"
    )
    print(f"Starting CONFIG: {len(best_cfg['strategies'])} strategies")

    iterate.write_config(best_cfg)
    best_score = iterate.evaluate(args.eval_maps, "factory_plan", "results")
    print(f"  baseline score: {best_score:.3f}\n")

    history: list[dict] = []
    log_fh.write(
        json.dumps(
            {
                "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "iter": 0,
                "cfg": best_cfg,
                "score": best_score,
                "accept": True,
                "best": best_score,
                "source": "baseline",
            }
        )
        + "\n"
    )
    log_fh.flush()

    print(f"{'iter':>4}  {'src':<6}  {'delta':>7}  {'score':>7}  {'best':>7}  {'acc':<4}")
    print("-" * 70)

    start = time.time()
    tried: set[tuple] = {iterate._config_signature(best_cfg)}
    llm_calls = 0

    for i in range(1, 1000):
        elapsed = time.time() - start
        if elapsed > args.budget_sec or llm_calls >= args.max_llm_calls:
            print(f"\nstopping at iter {i - 1} (elapsed={elapsed:.1f}s, llm_calls={llm_calls})")
            break

        # Build the prompt and call the LLM.
        prompt = PROMPT_TEMPLATE.format(
            lane_y_sets=SEARCH_ENUM_REPR["lane_y_sets"],
            asm_x_patterns=SEARCH_ENUM_REPR["asm_x_patterns"],
            smelter_offsets=SEARCH_ENUM_REPR["smelter_offsets"],
            miner_picks=SEARCH_ENUM_REPR["miner_picks"],
            max_route_values=SEARCH_ENUM_REPR["max_route_values"],
            resource_patterns=SEARCH_ENUM_REPR["resource_patterns"],
            n_current=len(best_cfg["strategies"]),
            current_config=json.dumps(best_cfg, indent=2),
            current_score=best_score,
            history=render_history(history),
        )
        t0 = time.time()
        raw = call_llm(prompt, args.model, args.relay)
        llm_calls += 1
        llm_latency = time.time() - t0

        candidate = parse_config(raw) if raw else None
        source = "llm"
        if candidate is None or not validate_config(candidate):
            # Fall back to random mutation so the loop still advances.
            candidate = iterate.mutate(best_cfg, rng)
            source = "fallback_random"

        cand_key = iterate._config_signature(candidate)
        if cand_key in tried:
            # If the LLM proposed a duplicate, force a random nudge.
            candidate = iterate.mutate(candidate, rng)
            cand_key = iterate._config_signature(candidate)
            source = source + "+random_nudge"
        tried.add(cand_key)

        iterate.write_config(candidate)
        score = iterate.evaluate(args.eval_maps, "factory_plan", "results")
        delta = score - best_score
        accept = score > best_score
        if accept:
            best_score = score
            best_cfg = candidate
        else:
            iterate.write_config(best_cfg)  # revert

        row = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "iter": i,
            "cfg": candidate,
            "score": score,
            "accept": accept,
            "best": best_score,
            "source": source,
            "llm_latency_sec": round(llm_latency, 2),
            "elapsed_sec": round(elapsed, 2),
        }
        history.append(row)
        log_fh.write(json.dumps(row) + "\n")
        log_fh.flush()

        print(
            f"{i:>4}  {source[:6]:<6}  {delta:>+7.2f}  {score:>7.2f}  {best_score:>7.2f}  "
            f"{('YES' if accept else 'no'):<4}  ({llm_latency:.1f}s)"
        )

    iterate.write_config(best_cfg)
    print(f"\nDone. Best CONFIG ({len(best_cfg['strategies'])} strategies):  {best_score:.3f}")
    print(f"\nFinal {args.bench_maps}-map bench of best CONFIG…")
    final = iterate.evaluate(args.bench_maps, "factory_plan", "results")
    print(f"  factory_plan ({args.bench_maps} maps) mean: {final:.3f}")

    log_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
