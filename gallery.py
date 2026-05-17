#!/usr/bin/env python3
"""Build a grid PNG of (planner × seed) layouts for visual reporting.

Each tile is one planner's layout on one seed, with score + wpm in the header.
Used at AutoResearch checkpoints to show what's actually changed.

Usage:
    python gallery.py                            # default: v0/v1/v2 × 3 seeds
    python gallery.py --seeds 25 18 11 --planners plans.v1_multi_lane plans.v2_dense_lanes
    python gallery.py --out results/checkpoint1.png
"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from auto_factory import generate_map, render_png, score_plan, simulate


DEFAULT_PLANNERS = ["plans.v0_naive", "plans.v1_multi_lane", "plans.v2_dense_lanes"]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[25, 11, 18])
    ap.add_argument("--planners", nargs="+", default=DEFAULT_PLANNERS)
    ap.add_argument("--width", type=int, default=20)
    ap.add_argument("--height", type=int, default=15)
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--cell-px", type=int, default=24, help="grid cell size in PNG")
    ap.add_argument("--out", default="results/gallery.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    tmp_dir = Path("results/_gallery_tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    planners = []
    for p in args.planners:
        planners.append((p, importlib.import_module(p)))

    # build all tiles, collect metadata
    tile_paths: dict[tuple[str, int], Path] = {}
    metas: dict[tuple[str, int], tuple[float, float, int]] = {}
    for planner_name, mod in planners:
        for seed in args.seeds:
            gmap = generate_map(seed=seed, width=args.width, height=args.height)
            p = mod.plan(gmap)
            sim = simulate(p, gmap, ticks=args.ticks)
            sb = score_plan(sim)
            title = (
                f"{planner_name}  seed={seed}  "
                f"score={sb.total:.1f}  wpm={sim.widgets_per_minute:.1f}"
            )
            tile_path = tmp_dir / f"{planner_name.replace('.','_')}_seed{seed}.png"
            render_png(p, gmap, tile_path, title=title, cell_px=args.cell_px)
            tile_paths[(planner_name, seed)] = tile_path
            metas[(planner_name, seed)] = (sb.total, sim.widgets_per_minute, len(p.buildings))

    # determine tile size from first tile
    first = Image.open(next(iter(tile_paths.values())))
    tw, th = first.size

    gap = 12
    margin = 24
    header_h = 36
    cols = len(args.seeds)
    rows = len(planners)
    W = margin * 2 + tw * cols + gap * (cols - 1)
    H = margin * 2 + header_h + th * rows + gap * (rows - 1)

    canvas = Image.new("RGB", (W, H), (250, 250, 250))
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=20)
    except OSError:
        title_font = ImageFont.load_default()

    header = f"Auto Factory — {rows} planners × {cols} seeds — {args.ticks} ticks/map"
    draw.text((margin, margin // 2), header, fill=(20, 20, 20), font=title_font)

    for ri, (planner_name, _mod) in enumerate(planners):
        for ci, seed in enumerate(args.seeds):
            x = margin + ci * (tw + gap)
            y = margin + header_h + ri * (th + gap)
            tile = Image.open(tile_paths[(planner_name, seed)])
            canvas.paste(tile, (x, y))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)

    # console summary
    print(f"\nGallery: {rows} planners × {cols} seeds")
    print(
        f"{'planner':<26}  " + "  ".join(f"seed={s:<5}" for s in args.seeds)
    )
    for planner_name, _ in planners:
        row = [f"{planner_name:<26}"]
        for seed in args.seeds:
            score, wpm, bld = metas[(planner_name, seed)]
            row.append(f"{score:>5.1f}/{wpm:>5.1f}wpm")
        print("  ".join(row))
    print(f"\n  out -> {out_path}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
