#!/usr/bin/env python3
"""Auto Factory evaluator.

Usage:
    python eval.py --maps 50
    python eval.py --maps 50 --planner plans.v1_multi_lane --label v1-baseline
    python eval.py --maps 5 --seed-base 100 --no-png --ascii

Generates N deterministic maps, runs the planner module's `plan(gmap)`
function on each, simulates the resulting factory, scores it, writes
results/summary.json + per-map PNGs, and appends one row to
results/runs.jsonl for cross-run tracking (AutoResearch-friendly).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib
import inspect
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from auto_factory import (
    generate_map,
    render_ascii,
    render_png,
    score_plan,
    simulate,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Auto Factory eval harness")
    ap.add_argument("--maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--width", type=int, default=20)
    ap.add_argument("--height", type=int, default=15)
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--ascii", action="store_true", help="print ASCII for first 3 maps")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument(
        "--planner",
        default="factory_plan",
        help="dotted module path exposing plan(gmap) "
        "(e.g. factory_plan, plans.v0_naive, plans.v1_multi_lane)",
    )
    ap.add_argument(
        "--label",
        default=None,
        help="optional tag attached to this run's row in runs.jsonl",
    )
    ap.add_argument(
        "--no-jsonl",
        action="store_true",
        help="skip appending to results/runs.jsonl",
    )
    return ap.parse_args()


def _load_planner(module_path: str):
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "plan"):
        raise SystemExit(f"planner {module_path!r} has no `plan` function")
    return mod


def _planner_hash(mod) -> str:
    """sha256 of the planner's source file (for reproducibility in run log)."""
    try:
        src = inspect.getsource(mod)
    except (OSError, TypeError):
        return "unknown"
    return "sha256:" + hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    planner_mod = _load_planner(args.planner)
    planner_hash = _planner_hash(planner_mod)

    results = []
    start = time.time()

    for i in range(args.maps):
        seed = args.seed_base + i
        gmap = generate_map(seed=seed, width=args.width, height=args.height)
        try:
            p = planner_mod.plan(gmap)
        except Exception as e:
            results.append(
                {
                    "seed": seed,
                    "score": -1000.0,
                    "valid": False,
                    "reason": f"planner_exception: {e!r}",
                    "buildings": 0,
                    "widgets_per_minute": 0.0,
                    "crossings": 0,
                    "congestion": 0,
                    "building_cost": 0.0,
                    "energy_total": 0.0,
                    "raw_per_minute": {},
                    "breakdown": {},
                }
            )
            continue

        sim = simulate(p, gmap, ticks=args.ticks)
        sb = score_plan(sim)

        rec = {
            "seed": seed,
            "score": round(sb.total, 3),
            "valid": sb.valid,
            "reason": sb.reason,
            "buildings": len(p.buildings),
            "widgets_per_minute": round(sim.widgets_per_minute, 3),
            "crossings": sim.crossings,
            "congestion": sim.congestion,
            "building_cost": sim.building_cost,
            "energy_total": sim.energy_total,
            "raw_per_minute": {k: round(v, 2) for k, v in sim.raw_per_minute.items()},
            "breakdown": sb.to_dict(),
        }
        results.append(rec)

        if args.ascii and i < 3:
            print(f"\n--- seed {seed} (score {rec['score']}) ---")
            print(render_ascii(p, gmap))

        if not args.no_png:
            png_path = out_dir / "plans" / f"{args.planner.replace('.', '_')}_seed_{seed:04d}.png"
            title = (
                f"{args.planner} seed={seed} score={rec['score']:.2f} "
                f"wpm={rec['widgets_per_minute']:.2f} valid={'Y' if sb.valid else 'N'}"
            )
            try:
                render_png(p, gmap, png_path, title=title)
            except Exception as e:
                rec["png_error"] = str(e)

    elapsed = time.time() - start

    valid = [r for r in results if r["valid"]]
    scores = [r["score"] for r in results]
    valid_scores = [r["score"] for r in valid]
    wpms = [r["widgets_per_minute"] for r in valid]

    summary: dict[str, Any] = {
        "planner": args.planner,
        "planner_hash": planner_hash,
        "label": args.label,
        "maps": args.maps,
        "seed_base": args.seed_base,
        "ticks_per_map": args.ticks,
        "width": args.width,
        "height": args.height,
        "elapsed_sec": round(elapsed, 2),
        "n_valid": len(valid),
        "n_invalid": args.maps - len(valid),
        "mean_score": round(statistics.fmean(scores), 3) if scores else 0.0,
        "median_score": round(statistics.median(scores), 3) if scores else 0.0,
        "best_score": round(max(scores), 3) if scores else 0.0,
        "worst_score": round(min(scores), 3) if scores else 0.0,
        "valid_mean_score": (
            round(statistics.fmean(valid_scores), 3) if valid_scores else 0.0
        ),
        "valid_mean_widgets_per_min": (
            round(statistics.fmean(wpms), 3) if wpms else 0.0
        ),
        "valid_max_widgets_per_min": round(max(wpms), 3) if wpms else 0.0,
        "top": sorted(results, key=lambda r: -r["score"])[: args.top],
        "bottom": sorted(results, key=lambda r: r["score"])[: args.top],
        "results": results,
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # ---- AutoResearch run log: one JSON line per eval, machine-readable ----
    if not args.no_jsonl:
        row = {
            "ts": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "planner": args.planner,
            "planner_hash": planner_hash,
            "label": args.label,
            "n_maps": args.maps,
            "seed_base": args.seed_base,
            "ticks": args.ticks,
            "width": args.width,
            "height": args.height,
            "elapsed_sec": round(elapsed, 2),
            "summary": {
                "valid": len(valid),
                "mean_score": summary["mean_score"],
                "median_score": summary["median_score"],
                "best_score": summary["best_score"],
                "worst_score": summary["worst_score"],
                "valid_mean_wpm": summary["valid_mean_widgets_per_min"],
                "valid_max_wpm": summary["valid_max_widgets_per_min"],
            },
            "scores": [r["score"] for r in results],
        }
        jsonl_path = out_dir / "runs.jsonl"
        with jsonl_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    # ---- console summary ----
    label = f" [{args.label}]" if args.label else ""
    print(
        f"\nAuto Factory eval{label} — planner={args.planner} "
        f"{args.maps} maps × {args.ticks} ticks in {elapsed:.1f}s"
    )
    print(f"  valid plans   : {len(valid)}/{args.maps}")
    print(f"  mean score    : {summary['mean_score']}")
    print(f"  median score  : {summary['median_score']}")
    print(f"  valid mean    : {summary['valid_mean_score']}")
    print(
        f"  valid mean wpm: {summary['valid_mean_widgets_per_min']} (max {summary['valid_max_widgets_per_min']})"
    )
    print(f"  best / worst  : {summary['best_score']} / {summary['worst_score']}")
    print(
        f"  top {args.top}: "
        + ", ".join(f"seed={r['seed']}({r['score']:.1f})" for r in summary["top"])
    )
    print(
        f"  bot {args.top}: "
        + ", ".join(f"seed={r['seed']}({r['score']:.1f})" for r in summary["bottom"])
    )
    print(f"\n  summary -> {out_dir / 'summary.json'}")
    if not args.no_jsonl:
        print(f"  run log -> {out_dir / 'runs.jsonl'}")
    if not args.no_png:
        print(f"  pngs    -> {out_dir / 'plans'}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
