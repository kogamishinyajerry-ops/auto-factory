#!/usr/bin/env python3
"""Render a score-distribution histogram across all 50 seeds, one strip per planner.

Reads results/runs.jsonl (latest row per planner) and produces a single PNG
with one horizontal histogram per planner, sorted by mean score. Useful at
checkpoint time to show how distribution shape changes (mean shift vs
worst-case improvement vs new peaks).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="results/runs.jsonl")
    ap.add_argument("--out", default="results/histogram.png")
    ap.add_argument("--bins", type=int, default=20)
    ap.add_argument(
        "--planners",
        nargs="+",
        default=None,
        help="restrict to specific planner names (default: all latest)",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    rows = [
        json.loads(line) for line in Path(args.runs).read_text().splitlines() if line.strip()
    ]
    # latest per planner
    latest: dict[str, dict] = {}
    for r in rows:
        if r["planner"] not in latest or r["ts"] > latest[r["planner"]]["ts"]:
            latest[r["planner"]] = r
    runs = list(latest.values())
    if args.planners:
        runs = [r for r in runs if r["planner"] in args.planners]
    runs.sort(key=lambda r: -r["summary"]["mean_score"])

    all_scores = [s for r in runs for s in r["scores"]]
    lo, hi = min(all_scores), max(all_scores)
    span = hi - lo if hi > lo else 1.0

    margin = 20
    label_w = 220
    strip_h = 70
    strip_w = 720
    H = margin * 2 + 36 + len(runs) * (strip_h + 8)
    W = margin * 2 + label_w + strip_w
    canvas = Image.new("RGB", (W, H), (250, 250, 250))
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=18)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=12)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font

    draw.text(
        (margin, margin // 2),
        f"score distribution — {len(runs)} planners × 50 seeds   range [{lo:.1f}, {hi:.1f}]",
        fill=(20, 20, 20),
        font=title_font,
    )

    bin_edges = [lo + i * span / args.bins for i in range(args.bins + 1)]

    base_y = margin + 36
    palette = [(200, 60, 60), (60, 120, 200), (60, 160, 80), (180, 130, 60), (140, 80, 180), (60, 160, 200)]

    # zero-line position in strip
    zero_frac = (0.0 - lo) / span if lo <= 0 <= hi else None

    for idx, r in enumerate(runs):
        scores = r["scores"]
        bins = [0] * args.bins
        for s in scores:
            i = min(args.bins - 1, int((s - lo) / span * args.bins))
            bins[i] += 1
        max_b = max(bins) if any(bins) else 1

        y = base_y + idx * (strip_h + 8)
        # label
        s = r["summary"]
        draw.text(
            (margin, y + 4),
            f"{r['planner']}",
            fill=(20, 20, 20),
            font=title_font,
        )
        draw.text(
            (margin, y + 30),
            f"  mean={s['mean_score']:>6.2f}  med={s['median_score']:>6.2f}",
            fill=(50, 50, 50),
            font=font,
        )
        draw.text(
            (margin, y + 48),
            f"  best={s['best_score']:>6.1f}  wrst={s['worst_score']:>6.1f}",
            fill=(50, 50, 50),
            font=font,
        )

        # strip background
        sx = margin + label_w
        sy = y
        draw.rectangle(
            [sx, sy, sx + strip_w, sy + strip_h], fill=(245, 245, 250), outline=(200, 200, 210)
        )
        # zero line
        if zero_frac is not None:
            zx = sx + int(zero_frac * strip_w)
            draw.line([(zx, sy), (zx, sy + strip_h)], fill=(180, 80, 80), width=1)

        # bars
        color = palette[idx % len(palette)]
        bin_w = strip_w / args.bins
        for bi, count in enumerate(bins):
            if count == 0:
                continue
            bh = int((count / max_b) * (strip_h - 8))
            bx0 = sx + int(bi * bin_w) + 1
            bx1 = sx + int((bi + 1) * bin_w) - 1
            by0 = sy + strip_h - bh - 2
            by1 = sy + strip_h - 2
            draw.rectangle([bx0, by0, bx1, by1], fill=color)

        # mean marker
        mean_frac = (s["mean_score"] - lo) / span
        mx = sx + int(mean_frac * strip_w)
        draw.line([(mx, sy), (mx, sy + strip_h)], fill=(20, 20, 20), width=2)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
