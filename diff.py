#!/usr/bin/env python3
"""A/B compare two planners on a single seed.

Renders a side-by-side PNG (baseline ⟂ candidate) plus a score-diff table.
Useful when iterating on factory_plan.py — pick a seed, see exactly what
the new plan does differently.

Usage:
    python diff.py --seed 22
    python diff.py --seed 25 --planner factory_plan --baseline plans.v1_multi_lane
    python diff.py --seed 7 --out results/diff_seed7.png
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from auto_factory import generate_map, render_png, score_plan, simulate


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--planner", default="factory_plan")
    ap.add_argument("--baseline", default="plans.v0_naive")
    ap.add_argument("--width", type=int, default=20)
    ap.add_argument("--height", type=int, default=15)
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument(
        "--out",
        default=None,
        help="output PNG path (default: results/diff_<seed>_<planner>_vs_<baseline>.png)",
    )
    return ap.parse_args()


def _eval_one(module_path: str, gmap, ticks: int) -> tuple[object, object, object]:
    mod = importlib.import_module(module_path)
    p = mod.plan(gmap)
    sim = simulate(p, gmap, ticks=ticks)
    sb = score_plan(sim)
    return p, sim, sb


def _composite(left_png: Path, right_png: Path, out_path: Path) -> None:
    """Glue two PNGs into a single side-by-side image with a divider."""
    from PIL import Image, ImageDraw

    a = Image.open(left_png)
    b = Image.open(right_png)
    gap = 16
    H = max(a.height, b.height)
    W = a.width + gap + b.width
    canvas = Image.new("RGB", (W, H), (230, 230, 230))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + gap, 0))
    draw = ImageDraw.Draw(canvas)
    mid = a.width + gap // 2
    draw.line([(mid, 0), (mid, H)], fill=(120, 120, 120), width=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def main() -> int:
    args = parse_args()
    gmap = generate_map(seed=args.seed, width=args.width, height=args.height)

    base_plan, base_sim, base_sb = _eval_one(args.baseline, gmap, args.ticks)
    cand_plan, cand_sim, cand_sb = _eval_one(args.planner, gmap, args.ticks)

    results_dir = Path("results/diff")
    results_dir.mkdir(parents=True, exist_ok=True)
    base_png = results_dir / f"_baseline_seed{args.seed}.png"
    cand_png = results_dir / f"_candidate_seed{args.seed}.png"

    base_title = (
        f"BASELINE  {args.baseline}  seed={args.seed}  "
        f"score={base_sb.total:.2f}  wpm={base_sim.widgets_per_minute:.2f}"
    )
    cand_title = (
        f"CANDIDATE {args.planner}  seed={args.seed}  "
        f"score={cand_sb.total:.2f}  wpm={cand_sim.widgets_per_minute:.2f}"
    )
    render_png(base_plan, gmap, base_png, title=base_title)
    render_png(cand_plan, gmap, cand_png, title=cand_title)

    if args.out:
        out_path = Path(args.out)
    else:
        a = args.planner.replace(".", "_")
        b = args.baseline.replace(".", "_")
        out_path = Path(f"results/diff_seed{args.seed}_{a}_vs_{b}.png")
    _composite(base_png, cand_png, out_path)

    # ---- scoreline ----
    delta = cand_sb.total - base_sb.total
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
    print(f"\nseed={args.seed}  ticks={args.ticks}  ({args.width}×{args.height})")
    print(f"  baseline  {args.baseline:<28}  score={base_sb.total:>7.2f}  wpm={base_sim.widgets_per_minute:>6.2f}  bld={len(base_plan.buildings):>3}  congest={base_sim.congestion}")
    print(f"  candidate {args.planner:<28}  score={cand_sb.total:>7.2f}  wpm={cand_sim.widgets_per_minute:>6.2f}  bld={len(cand_plan.buildings):>3}  congest={cand_sim.congestion}")
    print(f"  delta                                  score={delta:>+7.2f} {arrow}")
    print(f"\n  composite -> {out_path}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
