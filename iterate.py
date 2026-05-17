#!/usr/bin/env python3
"""Autonomous mutation loop for factory_plan.py CONFIG block.

Hill-climber with random restarts. Each iteration:
  1. Mutate the CONFIG dict (single-key swap mostly, occasional restart)
  2. Rewrite factory_plan.py between the AUTORESEARCH markers
  3. Subprocess: `python eval.py --planner factory_plan --maps N`
  4. Greedy-accept if mean_score improves; otherwise revert
  5. Append to results/iterate.jsonl

Budget = wall-clock seconds OR max iterations (whichever hits first).
On exit, factory_plan.py is left holding the best CONFIG found.

Usage:
    python iterate.py                          # 60s budget, 20-map eval
    python iterate.py --budget-sec 120 --eval-maps 30
    python iterate.py --max-iters 500 --seed 7
    python iterate.py --reset                  # start from a known weak config
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FACTORY_PLAN = HERE / "factory_plan.py"
DEFAULT_LOG_PATH = HERE / "results" / "iterate.jsonl"

CONFIG_MARKER_START = "# === AUTORESEARCH CONFIG START ==="
CONFIG_MARKER_END = "# === AUTORESEARCH CONFIG END ==="


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

# Search space PER STRATEGY. iterate.py mutates strategies inside CONFIG["strategies"].
# Phase B: 5 search dimensions instead of 3 — 6 × 6 × 3 × 3 × 6 = 1944
# single-strategy configs, exponential in portfolio size.
SEARCH_SPACE = {
    "lane_y_set": [
        "y_default", "y_v1", "y_shift", "y_narrow", "y_dense", "y_pair",
    ],
    "asm_x_pattern": [
        "all17", "all15", "all16",
        "stagger17_15", "stagger15_17", "stagger17_16",
    ],
    "smelter_offset": [2, 3, 4],
    "miner_pick": ["closest_y", "leftmost", "min_route"],
    "max_route_dist": [None, 10, 12, 15, 18, 25],
}

PORTFOLIO_CAP = 5  # max strategies kept in CONFIG["strategies"]

# Deliberately weak starting config used by --reset.
RESET_CONFIG = {
    "strategies": [
        {"lane_y_set": "y_v1", "asm_x_pattern": "all17", "smelter_offset": 3,
         "miner_pick": "closest_y", "max_route_dist": None}
    ]
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec", type=float, default=60.0)
    ap.add_argument("--max-iters", type=int, default=300)
    ap.add_argument(
        "--eval-maps",
        type=int,
        default=20,
        help="maps per evaluation (lower = faster iterations)",
    )
    ap.add_argument(
        "--bench-maps",
        type=int,
        default=50,
        help="final bench size after the loop terminates",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true", help="start from RESET_CONFIG instead of the target file's current CONFIG")
    ap.add_argument("--quiet", action="store_true")
    # Tournament hooks — let multiple iterate workers run in parallel.
    ap.add_argument(
        "--target-file",
        default=str(DEFAULT_FACTORY_PLAN),
        help="path to the planner module file to mutate (default: factory_plan.py)",
    )
    ap.add_argument(
        "--planner-name",
        default="factory_plan",
        help="dotted module name eval.py imports (must match --target-file's basename)",
    )
    ap.add_argument(
        "--log-file",
        default=str(DEFAULT_LOG_PATH),
        help="path to JSONL log (default: results/iterate.jsonl)",
    )
    ap.add_argument(
        "--eval-out-dir",
        default="results",
        help="--out-dir passed to eval.py (each worker should use a unique dir)",
    )
    return ap.parse_args()


# ---- factory_plan.py CONFIG block I/O ----------------------------------

def _extract_balanced_dict(block: str) -> str:
    """Find 'CONFIG = {' and return the full balanced-brace literal that follows."""
    eq = block.find("CONFIG")
    if eq < 0:
        raise SystemExit("CONFIG = ... not found between markers.")
    brace = block.find("{", eq)
    if brace < 0:
        raise SystemExit("opening '{' of CONFIG not found.")
    depth = 0
    i = brace
    in_str = False
    str_quote = ""
    while i < len(block):
        c = block[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == str_quote:
                in_str = False
        else:
            if c in ('"', "'"):
                in_str = True
                str_quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return block[brace : i + 1]
        i += 1
    raise SystemExit("CONFIG literal not balanced (unmatched braces).")


def read_config(path: Path = DEFAULT_FACTORY_PLAN) -> dict:
    text = path.read_text()
    s = text.find(CONFIG_MARKER_START)
    e = text.find(CONFIG_MARKER_END)
    if s < 0 or e < 0:
        raise SystemExit(
            f"AUTORESEARCH markers not found in {path} — refusing to mutate."
        )
    block = text[s + len(CONFIG_MARKER_START):e]
    literal = _extract_balanced_dict(block)
    import ast

    return ast.literal_eval(literal)


def write_config(cfg: dict, path: Path = DEFAULT_FACTORY_PLAN) -> None:
    text = path.read_text()
    s = text.find(CONFIG_MARKER_START)
    e = text.find(CONFIG_MARKER_END)
    rendered = "CONFIG = " + _render_python(cfg, indent=0)
    new_block = (
        f"{CONFIG_MARKER_START}\n"
        f"# (iterate.py rewrites between these markers; hand-editing is fine too)\n"
        f"{rendered}\n"
    )
    new_text = text[:s] + new_block + text[e:]
    path.write_text(new_text)


def _render_python(v, indent: int = 0) -> str:
    """Tiny pretty-printer that handles None/strings/ints/lists/dicts the way
    Python source would expect (avoids json's lowercase null)."""
    pad = "    " * indent
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        inner = ",\n".join(f"{pad}    {_render_python(x, indent + 1)}" for x in v)
        return f"[\n{inner}\n{pad}]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        inner = ",\n".join(
            f"{pad}    {json.dumps(k)}: {_render_python(val, indent + 1)}"
            for k, val in v.items()
        )
        return f"{{\n{inner}\n{pad}}}"
    return repr(v)


# ---- evaluation --------------------------------------------------------


def evaluate(maps: int, planner_name: str, eval_out_dir: str) -> float:
    """Run eval.py against the given planner and return mean_score."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HERE / "eval.py"),
            "--planner",
            planner_name,
            "--maps",
            str(maps),
            "--no-png",
            "--no-jsonl",
            "--out-dir",
            eval_out_dir,
        ],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return float("-inf")
    summary_path = Path(eval_out_dir)
    if not summary_path.is_absolute():
        summary_path = HERE / summary_path
    summary = json.loads((summary_path / "summary.json").read_text())
    return float(summary["mean_score"])


# ---- mutation ----------------------------------------------------------


def _random_strategy(rng: random.Random) -> dict:
    return {k: rng.choice(vs) for k, vs in SEARCH_SPACE.items()}


def _mutate_strategy(s: dict, rng: random.Random) -> dict:
    """Single-key swap inside one strategy dict."""
    new = dict(s)
    k = rng.choice(list(SEARCH_SPACE.keys()))
    choices = [v for v in SEARCH_SPACE[k] if v != s.get(k)]
    if choices:
        new[k] = rng.choice(choices)
    return new


def mutate(cfg: dict, rng: random.Random) -> dict:
    """Return a new CONFIG by perturbing strategies. Six mutation kinds:
       - tweak:   change one key in a random existing strategy
       - replace: swap one existing strategy for a random new one
       - add:     append a random strategy (if portfolio not at cap)
       - remove:  drop a random strategy (if portfolio > 1)
       - restart_single:  collapse to a single random strategy
       - restart_portfolio: rebuild with 2-4 random strategies
    """
    strategies = [dict(s) for s in cfg["strategies"]]
    roll = rng.random()
    n = len(strategies)

    if roll < 0.05:
        # full restart with portfolio of 2-4 random strategies
        k = rng.randint(2, 4)
        strategies = [_random_strategy(rng) for _ in range(k)]
    elif roll < 0.10:
        # collapse to a single random strategy
        strategies = [_random_strategy(rng)]
    elif roll < 0.30 and n < PORTFOLIO_CAP:
        # add
        strategies.append(_random_strategy(rng))
    elif roll < 0.45 and n > 1:
        # remove
        i = rng.randrange(n)
        strategies.pop(i)
    elif roll < 0.65 and n > 0:
        # replace one
        i = rng.randrange(n)
        strategies[i] = _random_strategy(rng)
    else:
        # tweak one
        i = rng.randrange(n) if n > 0 else 0
        if n == 0:
            strategies = [_random_strategy(rng)]
        else:
            strategies[i] = _mutate_strategy(strategies[i], rng)

    # dedup within a portfolio so identical strategies don't waste budget
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for s in strategies:
        key = tuple(sorted(s.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    if not deduped:
        deduped = [_random_strategy(rng)]

    return {"strategies": deduped}


def _config_signature(cfg: dict) -> tuple:
    """Order-insensitive signature of a CONFIG (so we dedup attempts).
    Values are stringified before sorting so None vs int compares cleanly."""
    return tuple(sorted(
        tuple((k, repr(v)) for k, v in sorted(s.items()))
        for s in cfg["strategies"]
    ))


# ---- main loop ---------------------------------------------------------


def main() -> int:
    args = parse_args()
    target = Path(args.target_file)
    if not target.is_absolute():
        target = HERE / target
    log_path = Path(args.log_file)
    if not log_path.is_absolute():
        log_path = HERE / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a")

    rng = random.Random(args.seed)

    if args.reset:
        initial_cfg = dict(RESET_CONFIG)
        write_config(initial_cfg, path=target)
    else:
        initial_cfg = read_config(path=target)

    print(f"AutoResearch loop — budget={args.budget_sec}s, max_iters={args.max_iters}, eval_maps={args.eval_maps}")
    print(f"  target file: {target.name}   planner: {args.planner_name}")
    print(f"Starting CONFIG: {initial_cfg}")

    best_cfg = dict(initial_cfg)
    best_score = evaluate(args.eval_maps, args.planner_name, args.eval_out_dir)
    write_config(best_cfg, path=target)  # ensure file matches
    print(f"  baseline score: {best_score:.3f}\n")

    log_fh.write(
        json.dumps(
            {
                "ts": _now_iso(),
                "iter": 0,
                "cfg": best_cfg,
                "score": best_score,
                "accept": True,
                "best": best_score,
                "mutation_type": "baseline",
            }
        )
        + "\n"
    )
    log_fh.flush()

    print(f"{'iter':>4}  {'delta':>7}  {'score':>7}  {'best':>7}  {'acc':<4}  cfg")
    print("-" * 110)

    start = time.time()
    tried: set[tuple] = {_config_signature(best_cfg)}
    for i in range(1, args.max_iters + 1):
        elapsed = time.time() - start
        if elapsed > args.budget_sec:
            print(f"\nbudget exhausted at {elapsed:.1f}s")
            break

        candidate = mutate(best_cfg, rng)
        cand_key = _config_signature(candidate)
        retries = 0
        while cand_key in tried and retries < 10:
            candidate = mutate(best_cfg, rng)
            cand_key = _config_signature(candidate)
            retries += 1
        if cand_key in tried:
            continue
        tried.add(cand_key)

        write_config(candidate, path=target)
        score = evaluate(args.eval_maps, args.planner_name, args.eval_out_dir)
        delta = score - best_score
        accept = score > best_score
        if accept:
            best_score = score
            best_cfg = candidate
        else:
            write_config(best_cfg, path=target)  # revert

        log_fh.write(
            json.dumps(
                {
                    "ts": _now_iso(),
                    "iter": i,
                    "cfg": candidate,
                    "score": score,
                    "accept": accept,
                    "best": best_score,
                    "elapsed_sec": round(elapsed, 2),
                }
            )
            + "\n"
        )
        log_fh.flush()

        if not args.quiet:
            sigs = "|".join(
                f"{s['lane_y_set'][2:6]}/{s['asm_x_pattern'][:5]}/{s['smelter_offset']}/"
                f"{s['miner_pick'][:3]}/{s['max_route_dist']}"
                for s in candidate["strategies"]
            )
            print(
                f"{i:>4}  {delta:>+7.2f}  {score:>7.2f}  {best_score:>7.2f}  "
                f"{('YES' if accept else 'no'):<4}  [{len(candidate['strategies'])}] {sigs}"
            )

    # finalise
    write_config(best_cfg, path=target)
    print(f"\nLoop done. Best CONFIG: {best_cfg}")
    print(f"  best score (eval_maps={args.eval_maps}):  {best_score:.3f}")
    print(f"\nFinal {args.bench_maps}-map bench of best CONFIG…")
    final = evaluate(args.bench_maps, args.planner_name, args.eval_out_dir)
    print(f"  {args.planner_name} ({args.bench_maps} maps) mean: {final:.3f}")
    log_fh.write(
        json.dumps(
            {
                "ts": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "iter": -1,
                "kind": "final",
                "cfg": best_cfg,
                "bench_maps": args.bench_maps,
                "bench_score": final,
            }
        )
        + "\n"
    )
    log_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
