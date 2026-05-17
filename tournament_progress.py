#!/usr/bin/env python3
"""Render all tournament workers' convergence curves on one chart.

Reads every results/_workers/w*/iterate.jsonl and overlays each worker's
score trajectory in a different colour, with the merged-portfolio score
annotated at the top.

Usage:
    python tournament_progress.py
    python tournament_progress.py --out results/checkpoint5_tournament.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PALETTE = [
    (200, 60, 60),
    (60, 120, 200),
    (60, 160, 80),
    (180, 130, 60),
    (140, 80, 180),
    (60, 160, 200),
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers-dir", default="results/_workers")
    ap.add_argument("--tournament-json", default="results/tournament.json")
    ap.add_argument("--out", default="results/checkpoint5_tournament.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    workers_dir = Path(args.workers_dir)
    logs = sorted(workers_dir.glob("w*/iterate.jsonl"))
    if not logs:
        print(f"no worker logs in {workers_dir}")
        return 1

    workers = []
    for log in logs:
        rows = [
            json.loads(line)
            for line in log.read_text().splitlines()
            if line.strip()
        ]
        rows = [r for r in rows if r.get("iter", -1) >= 0]
        if rows:
            workers.append((log.parent.name, rows))

    # global axes
    all_scores: list[float] = []
    for _, rows in workers:
        for r in rows:
            all_scores.append(r["score"])
            all_scores.append(r["best"])
    max_iter = max((r["iter"] for _, rows in workers for r in rows), default=1)
    lo = min(all_scores)
    hi = max(all_scores)
    span = max(1e-6, hi - lo)

    margin = 60
    W, H = 1200, 620
    canvas = Image.new("RGB", (W, H), (252, 252, 252))
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=20)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=13)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=11)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    px0, py0 = margin, margin + 32
    px1, py1 = W - margin - 240, H - margin
    draw.rectangle([px0, py0, px1, py1], outline=(180, 180, 180))

    def xy(it: int, sc: float) -> tuple[int, int]:
        x = px0 + int((it / max_iter) * (px1 - px0))
        y = py1 - int((sc - lo) / span * (py1 - py0))
        return x, y

    # zero line
    if lo <= 0 <= hi:
        _, zy = xy(0, 0.0)
        draw.line([(px0, zy), (px1, zy)], fill=(220, 100, 100), width=1)

    # quarter gridlines
    for frac in (0.25, 0.5, 0.75):
        gy = py1 - int(frac * (py1 - py0))
        draw.line([(px0, gy), (px1, gy)], fill=(235, 235, 240), width=1)
        val = lo + frac * span
        draw.text((px0 - 40, gy - 6), f"{val:.1f}", fill=(120, 120, 120), font=small)

    draw.text((px0 - 40, py0 - 8), f"{hi:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0 - 40, py1 - 6), f"{lo:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0, py1 + 6), "iter 0", fill=(80, 80, 80), font=small)
    draw.text((px1 - 36, py1 + 6), f"iter {max_iter}", fill=(80, 80, 80), font=small)

    # plot each worker
    for idx, (name, rows) in enumerate(workers):
        color = PALETTE[idx % len(PALETTE)]
        # attempts as tiny dots
        for r in rows:
            x, y = xy(r["iter"], r["score"])
            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=color + (0,)[:0])
        # running-best line
        pts = [xy(r["iter"], r["best"]) for r in rows]
        if len(pts) > 1:
            draw.line(pts, fill=color, width=2)

    # title
    n_workers = len(workers)
    title = f"Tournament — {n_workers} parallel iterate workers, score curves overlaid"
    draw.text((margin, 16), title, fill=(20, 20, 20), font=title_font)

    # legend + final scores
    lx = px1 + 32
    ly = py0
    draw.text((lx, ly), "worker  best", fill=(40, 40, 40), font=font)
    for idx, (name, rows) in enumerate(workers):
        color = PALETTE[idx % len(PALETTE)]
        best_score = max(r["best"] for r in rows) if rows else 0
        draw.line([(lx, ly + 28 + idx * 22), (lx + 14, ly + 28 + idx * 22)], fill=color, width=3)
        draw.text(
            (lx + 22, ly + 22 + idx * 22),
            f"{name}   {best_score:>6.2f}",
            fill=(40, 40, 40),
            font=font,
        )

    # merged portfolio annotation
    summary_path = Path(args.tournament_json)
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        merged_score = summary.get("merged_score", float("nan"))
        n_merged = summary.get("n_merged_strategies", 0)
        annot_y = ly + 28 + len(workers) * 22 + 14
        draw.text(
            (lx, annot_y),
            "merged portfolio",
            fill=(0, 0, 0),
            font=font,
        )
        draw.text(
            (lx, annot_y + 18),
            f"  {n_merged} strategies",
            fill=(60, 60, 60),
            font=small,
        )
        draw.text(
            (lx, annot_y + 34),
            f"  score = {merged_score:.2f}",
            fill=(0, 100, 0) if merged_score == merged_score else (180, 0, 0),
            font=font,
        )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out)
    print(f"  out -> {args.out}")
    print(f"  {len(workers)} workers, {sum(len(r) for _, r in workers)} total attempts")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
