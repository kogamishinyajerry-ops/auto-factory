#!/usr/bin/env python3
"""Phase L variance + model-strength summary plot.

Reads all results/tournament_*.json files and plots:
  - left: bench score as dots, grouped by (model, workers).
          Shows mean+std for gpt-5.4 4-worker group (the variance reps).
  - right: per-worker individual scores (across reps), showing whether
           the LLM is generating consistently good or wildly variable seeds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


KNOWN_RUNS = [
    # (path, label, model, workers, seed_base, color)
    ("results/tournament_llm_seeded.json",       "L.2-B  gpt-5.4 seed_base=600",
     "gpt-5.4", 4, 600, (180, 100, 100)),
    ("results/tournament_gpt54_seed400.json",    "L.2-A  gpt-5.4 seed_base=400",
     "gpt-5.4", 4, 400, (180, 100, 100)),
    ("results/tournament_gpt55_xhigh.json",      "L.1   gpt-5.5 xhigh seed_base=500",
     "gpt-5.5", 4, 500, (40, 160, 90)),
    ("results/tournament_llm_seeded_6w.json",    "K     gpt-5.4 6 workers seed_base=300",
     "gpt-5.4", 6, 300, (155, 100, 200)),
]

# Phase J's original 43.83 result lives in commit 80e9860's
# results/tournament_llm_seeded.json — we hand-record it here since
# the file may have been overwritten by L.2-B.
PHASE_J_RECORD = {
    "label": "J     gpt-5.4 seed_base=200 (original SOTA)",
    "model": "gpt-5.4",
    "workers": 4,
    "seed_base": 200,
    "merged_bench_score": 43.828,
    "worker_finals": [35.33, 39.63, 37.72, 35.53],
    "color": (60, 130, 200),
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/checkpoint11_variance.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    runs = [dict(PHASE_J_RECORD)]
    for (path, label, model, workers, seed_base, color) in KNOWN_RUNS:
        p = Path(path)
        if not p.exists():
            continue
        j = json.loads(p.read_text())
        bench = j.get("merged_bench_score")
        if bench is None or bench != bench:  # NaN check
            continue
        worker_finals = [w["score"] for w in j.get("worker_results", [])]
        runs.append({
            "label": label, "model": model, "workers": workers,
            "seed_base": seed_base,
            "merged_bench_score": bench,
            "worker_finals": worker_finals,
            "color": color,
        })

    # === Plot setup ===
    W, H = 1400, 720
    img = Image.new("RGB", (W, H), (250, 250, 252))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=22)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=13)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=11)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    draw.text(
        (40, 18),
        "Phase L — variance study & gpt-5.4 vs gpt-5.5 xhigh comparison",
        fill=(20, 20, 20), font=title_font,
    )

    # === LEFT: merged bench score per run ===
    bx0, by0, bx1, by1 = 60, 90, 640, 580
    draw.rectangle([bx0, by0, bx1, by1], outline=(180, 180, 180))
    draw.text((bx0, by0 - 22),
              "Merged 50-map bench per run (dots = independent runs):",
              fill=(40, 40, 40), font=font)

    all_scores = [r["merged_bench_score"] for r in runs]
    lo, hi = min(all_scores) * 0.9, max(all_scores) * 1.02
    span = hi - lo

    def y_for(s: float) -> int:
        return by1 - int((s - lo) / span * (by1 - by0))

    # axis ticks
    for tick in (lo, (lo + hi) / 2, hi):
        gy = y_for(tick)
        draw.line([(bx0, gy), (bx1, gy)], fill=(235, 235, 240), width=1)
        draw.text((bx0 - 38, gy - 6), f"{tick:.1f}", fill=(120, 120, 120), font=small)

    # group gpt-5.4 4w runs (J + L.2-A + L.2-B) for variance band
    g54_4w = [r for r in runs if r["model"] == "gpt-5.4" and r["workers"] == 4]
    g54_4w.sort(key=lambda r: r["seed_base"])
    if g54_4w:
        scores = [r["merged_bench_score"] for r in g54_4w]
        mean = sum(scores) / len(scores)
        var = sum((s - mean) ** 2 for s in scores) / max(1, len(scores) - 1)
        std = var ** 0.5

        # draw band: mean ± std as a translucent rectangle on the left
        band_x0 = bx0 + 30
        band_x1 = bx0 + 200
        band_top = y_for(mean + std)
        band_bot = y_for(mean - std)
        for y in range(min(band_top, band_bot), max(band_top, band_bot) + 1, 2):
            draw.line(
                [(band_x0, y), (band_x1, y)],
                fill=(220, 200, 200), width=1,
            )
        # mean line
        mean_y = y_for(mean)
        draw.line(
            [(band_x0 - 4, mean_y), (band_x1 + 4, mean_y)],
            fill=(180, 100, 100), width=2,
        )
        draw.text(
            (band_x0, band_top - 16),
            f"gpt-5.4 4w  mean {mean:.2f} ± {std:.2f}  (N={len(scores)})",
            fill=(180, 100, 100), font=small,
        )

    # plot dots for each run
    cluster_x = {"gpt-5.4|4": bx0 + 100, "gpt-5.4|6": bx0 + 320, "gpt-5.5|4": bx0 + 490}
    for r in runs:
        cx = cluster_x.get(f"{r['model']}|{r['workers']}", bx0 + 50)
        cy = y_for(r["merged_bench_score"])
        # jitter slightly so overlapping seed_bases are visible
        cx += (r["seed_base"] % 100) // 25 * 10
        draw.ellipse(
            [cx - 7, cy - 7, cx + 7, cy + 7],
            fill=r["color"], outline=(0, 0, 0),
        )
        draw.text(
            (cx + 12, cy - 7),
            f"{r['merged_bench_score']:.2f}",
            fill=(20, 20, 20), font=small,
        )
        draw.text(
            (cx + 12, cy + 5),
            f"seed_base={r['seed_base']}",
            fill=(80, 80, 80), font=small,
        )

    # group labels under x-axis
    for (key, cx) in cluster_x.items():
        model, workers = key.split("|")
        draw.text(
            (cx - 24, by1 + 8),
            f"{model}",
            fill=(40, 40, 40), font=small,
        )
        draw.text(
            (cx - 24, by1 + 22),
            f"{workers}w",
            fill=(80, 80, 80), font=small,
        )

    # SOTA marker — line at max
    sota = max(all_scores)
    sota_y = y_for(sota)
    draw.line([(bx0, sota_y), (bx1, sota_y)], fill=(50, 170, 90), width=1)
    draw.text(
        (bx1 - 130, sota_y - 14),
        f"SOTA: {sota:.2f}",
        fill=(50, 170, 90), font=small,
    )

    # === RIGHT: per-worker individual final scores across runs ===
    rx0, ry0, rx1, ry1 = 700, 90, W - 60, 580
    draw.rectangle([rx0, ry0, rx1, ry1], outline=(180, 180, 180))
    draw.text((rx0, ry0 - 22),
              "Per-worker individual 50-map scores (each dot = one worker):",
              fill=(40, 40, 40), font=font)

    all_wf = []
    for r in runs:
        all_wf.extend(r["worker_finals"])
    if all_wf:
        wlo, whi = min(all_wf) * 0.95, max(all_wf) * 1.05
        wspan = whi - wlo

        def wy(s: float) -> int:
            return ry1 - int((s - wlo) / wspan * (ry1 - ry0))

        for tick in (wlo, (wlo + whi) / 2, whi):
            gy = wy(tick)
            draw.line([(rx0, gy), (rx1, gy)], fill=(235, 235, 240), width=1)
            draw.text((rx0 - 38, gy - 6), f"{tick:.1f}", fill=(120, 120, 120), font=small)

        # one column per run
        col_w = (rx1 - rx0) // (len(runs) + 1)
        for ri, r in enumerate(runs):
            col_x = rx0 + (ri + 1) * col_w
            for wf in r["worker_finals"]:
                draw.ellipse(
                    [col_x - 5, wy(wf) - 5, col_x + 5, wy(wf) + 5],
                    fill=r["color"], outline=(0, 0, 0),
                )
            # run label
            for j, word in enumerate(r["label"].split("  ")[:2]):
                draw.text(
                    (col_x - 30, ry1 + 6 + j * 14),
                    word,
                    fill=(80, 80, 80), font=small,
                )

    # === FOOTER: summary table ===
    fy = 600
    draw.text((40, fy), "Run summary:", fill=(40, 40, 40), font=font)
    fy += 22
    rows_sorted = sorted(runs, key=lambda r: -r["merged_bench_score"])
    for r in rows_sorted:
        marker = "⭐" if r["merged_bench_score"] == sota else "  "
        max_worker = max(r["worker_finals"]) if r["worker_finals"] else 0
        draw.text(
            (60, fy),
            f"{marker}  {r['label']:<48s}  bench {r['merged_bench_score']:.2f}    max-worker {max_worker:.2f}",
            fill=(40, 40, 40), font=small,
        )
        fy += 16

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
