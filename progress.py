#!/usr/bin/env python3
"""Plot iterate.py's convergence curve from results/iterate.jsonl.

Three series:
  - gray dots:   every attempted candidate's score
  - red line:    running best-so-far
  - green dots:  accepted mutations (overlaid)

Plus a row of annotations showing the best CONFIG found and which mutations
landed it.

Usage:
    python progress.py
    python progress.py --out results/progress.png --since 2026-05-17T15:00:00Z
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="results/iterate.jsonl")
    ap.add_argument("--out", default="results/progress.png")
    ap.add_argument(
        "--since",
        default=None,
        help="ISO timestamp; only rows after this (use to plot a specific run)",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"no log at {log_path}")
        return 1

    from PIL import Image, ImageDraw, ImageFont

    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    if args.since:
        rows = [r for r in rows if r.get("ts", "") >= args.since]
    rows = [r for r in rows if r.get("iter", 0) >= 0]  # drop "final" sentinel
    if not rows:
        print("no rows match")
        return 1

    iters = [r["iter"] for r in rows]
    scores = [r["score"] for r in rows]
    bests = [r["best"] for r in rows]
    accepts = [(r["iter"], r["score"]) for r in rows if r["accept"]]

    lo = min(scores + bests)
    hi = max(scores + bests)
    span = max(1e-6, hi - lo)
    n_iter = max(1, iters[-1])

    margin = 60
    W, H = 1080, 540
    canvas = Image.new("RGB", (W, H), (252, 252, 252))
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=18)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=12)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=10)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    # plot area
    px0, py0 = margin, margin + 24
    px1, py1 = W - margin, H - margin

    # axes
    draw.rectangle([px0, py0, px1, py1], outline=(180, 180, 180))

    def xy(i: int, s: float) -> tuple[int, int]:
        x = px0 + int((i / n_iter) * (px1 - px0))
        y = py1 - int((s - lo) / span * (py1 - py0))
        return x, y

    # zero line if in range
    if lo <= 0 <= hi:
        _, zy = xy(0, 0.0)
        draw.line([(px0, zy), (px1, zy)], fill=(220, 100, 100), width=1)
        draw.text((px1 + 4, zy - 6), "0", fill=(180, 80, 80), font=small)

    # gridlines: every 25% of span
    for frac in (0.25, 0.5, 0.75):
        gy = py1 - int(frac * (py1 - py0))
        draw.line([(px0, gy), (px1, gy)], fill=(235, 235, 240), width=1)
        val = lo + frac * span
        draw.text((px0 - 36, gy - 6), f"{val:.1f}", fill=(120, 120, 120), font=small)

    # axis labels at ends
    draw.text((px0 - 40, py0 - 8), f"{hi:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0 - 40, py1 - 6), f"{lo:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0, py1 + 6), "iter 0", fill=(80, 80, 80), font=small)
    draw.text((px1 - 30, py1 + 6), f"iter {n_iter}", fill=(80, 80, 80), font=small)

    # all attempts (gray dots)
    for i, s in zip(iters, scores):
        x, y = xy(i, s)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(160, 160, 170))

    # running best (red line)
    pts = [xy(i, b) for i, b in zip(iters, bests)]
    if len(pts) > 1:
        draw.line(pts, fill=(200, 40, 40), width=2)

    # accepted (green dots, overlaid)
    for i, s in accepts:
        x, y = xy(i, s)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(40, 140, 60), width=2)

    # title + summary
    final_best = bests[-1]
    n_accepts = len(accepts)
    title = (
        f"AutoResearch convergence — {len(rows)} attempts, "
        f"{n_accepts} accepted, final best = {final_best:.2f}"
    )
    draw.text((margin, 16), title, fill=(20, 20, 20), font=title_font)

    # legend
    lx = px1 - 220
    ly = py0 + 12
    draw.ellipse([lx, ly + 2, lx + 6, ly + 8], fill=(160, 160, 170))
    draw.text((lx + 12, ly), "attempt", fill=(50, 50, 50), font=small)
    draw.line([(lx, ly + 22), (lx + 12, ly + 22)], fill=(200, 40, 40), width=2)
    draw.text((lx + 16, ly + 16), "running best", fill=(50, 50, 50), font=small)
    draw.ellipse([lx, ly + 34, lx + 6, ly + 40], outline=(40, 140, 60), width=2)
    draw.text((lx + 12, ly + 32), "accepted", fill=(50, 50, 50), font=small)

    # final config annotation (last accepted)
    if accepts:
        final_row = next((r for r in reversed(rows) if r["accept"]), rows[0])
        cfg = final_row["cfg"]
        cfg_text = "best CONFIG: " + "  ".join(f"{k}={v}" for k, v in cfg.items())
        draw.text((margin, H - margin + 30), cfg_text, fill=(40, 90, 40), font=font)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out)
    print(f"  out -> {args.out}")
    print(f"  attempts={len(rows)}  accepted={n_accepts}  final_best={final_best:.2f}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
