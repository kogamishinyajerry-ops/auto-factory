#!/usr/bin/env python3
"""SOTA timeline visualisation across all phases.

A single PNG showing 50-map bench scores per checkpoint over the project
arc, with phase labels and key inflection-point annotations. Reads
hand-curated milestones plus reads merged_bench_score from any
tournament_*.json / champion_*.json / greedy_*.json files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


# (label, score, color)
MILESTONES = [
    ("A · v0 naive",                  7.0,  (180, 180, 180), "baseline"),
    ("A · v1 multi-lane (hand)",     18.6,  (160, 160, 160), "baseline"),
    ("A · v3 greedy hand-search",    26.8,  (140, 140, 140), "baseline"),
    ("B · single-worker random",     38.8,  (180, 100, 100), "random"),
    ("G · 4-worker tournament",      43.2,  (155, 100, 200), "random"),
    ("H · LLM-only (12 attempts)",   30.5,  (60, 130, 200),  "llm"),
    ("I · hybrid (LLM-meta + rand)", 36.1,  (40, 160, 90),   "llm"),
    ("J · gpt-5.4 LLM-seeded",       43.8,  (60, 130, 200),  "llm"),
    ("K · 6-worker scale-up",        41.1,  (200, 150, 50),  "neg"),
    ("L.1 · gpt-5.5 xhigh",          44.88, (40, 160, 90),   "llm"),
    ("L.2-A · gpt-5.4 rep",          43.05, (200, 150, 150), "llm"),
    ("L.2-B · gpt-5.4 rep",          41.16, (200, 150, 150), "llm"),
    ("M.3 · gpt-5.5 rep 2",          41.89, (160, 200, 160), "llm"),
    ("M.1 · Champion-of-Champions",  44.09, (200, 100, 100), "neg"),
    ("M.1' · Greedy submodular",     49.79, (50, 170, 90),   "llm"),
    ("O.3 · expanded space K=39",    52.39, (50, 170, 90),   "llm"),
    ("P.3 · grown pool K=44",        53.19, (50, 170, 90),   "sota"),
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/checkpoint12_sota_timeline.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1500, 720
    img = Image.new("RGB", (W, H), (250, 250, 252))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=24)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=14)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=11)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    draw.text(
        (40, 18),
        "Auto Factory — SOTA timeline across all phases (50-map bench)",
        fill=(20, 20, 20), font=title_font,
    )

    # plot area
    px0, py0 = 80, 80
    px1, py1 = W - 80, H - 100

    draw.rectangle([px0, py0, px1, py1], outline=(180, 180, 180))

    lo = 0.0
    hi = 55.0
    span = hi - lo
    n = len(MILESTONES)
    dx = (px1 - px0) / max(1, n - 1)

    # grid
    for tick in (10, 20, 30, 40, 50):
        y = py1 - int((tick - lo) / span * (py1 - py0))
        draw.line([(px0, y), (px1, y)], fill=(235, 235, 240), width=1)
        draw.text((px0 - 30, y - 6), f"{tick}", fill=(120, 120, 120), font=small)

    # find best running SOTA over time
    running_best = float("-inf")
    sota_points = []
    for i, (label, score, color, _kind) in enumerate(MILESTONES):
        if score > running_best:
            running_best = score
            sota_points.append((i, score))

    # draw SOTA envelope (only forward — running max)
    env_pts = []
    cur_max = float("-inf")
    for i, (_label, score, _color, _kind) in enumerate(MILESTONES):
        x = px0 + int(i * dx)
        cur_max = max(cur_max, score)
        y = py1 - int((cur_max - lo) / span * (py1 - py0))
        env_pts.append((x, y))
    # fill area under SOTA
    poly = [(env_pts[0][0], py1)] + env_pts + [(env_pts[-1][0], py1)]
    draw.polygon(poly, fill=(240, 250, 240))
    # SOTA envelope line
    draw.line(env_pts, fill=(50, 170, 90), width=2)

    # plot each phase as a dot
    for i, (label, score, color, kind) in enumerate(MILESTONES):
        x = px0 + int(i * dx)
        y = py1 - int((score - lo) / span * (py1 - py0))
        # dot
        radius = 8 if kind == "sota" else 5
        draw.ellipse([x - radius, y - radius, x + radius, y + radius],
                     fill=color, outline=(0, 0, 0))
        # score label above dot
        score_txt = f"{score:.2f}" if score < 100 else f"{int(score)}"
        draw.text((x - 14, y - 22), score_txt, fill=(20, 20, 20), font=small)
        # rotated phase label below
        # since PIL doesn't easily rotate text, stack vertically
        for j, ch in enumerate(label):
            if j > 30:
                break
            draw.text((x - 4, py1 + 6 + j * 9), ch, fill=(40, 40, 40), font=small)

    # SOTA markers
    for (i, score) in sota_points:
        x = px0 + int(i * dx)
        y = py1 - int((score - lo) / span * (py1 - py0))
        draw.ellipse([x - 12, y - 12, x + 12, y + 12],
                     outline=(50, 170, 90), width=2)

    # legend
    legend_y = 60
    cats = [
        ("hand baselines", (160, 160, 160)),
        ("random search", (180, 100, 100)),
        ("LLM-driven", (60, 130, 200)),
        ("negative result", (200, 100, 100)),
        ("SOTA", (50, 170, 90)),
    ]
    for i, (name, color) in enumerate(cats):
        cx = 60 + i * 200
        draw.ellipse([cx, legend_y, cx + 12, legend_y + 12],
                     fill=color, outline=(0, 0, 0))
        draw.text((cx + 18, legend_y - 1), name,
                  fill=(40, 40, 40), font=small)

    # current SOTA callout
    sota = max(s for _l, s, _c, _k in MILESTONES)
    sota_label = next(l for l, s, _c, _k in MILESTONES if s == sota)
    draw.text(
        (px1 - 380, py0 + 10),
        f"current SOTA: {sota:.2f}  ({sota_label})",
        fill=(20, 100, 50), font=font,
    )
    draw.text(
        (px1 - 380, py0 + 30),
        "from 7.0 (v0 naive) → 49.79 (M.1' greedy submodular)",
        fill=(40, 80, 40), font=small,
    )
    draw.text(
        (px1 - 380, py0 + 46),
        f"+612% improvement over the hand-coded v0 baseline",
        fill=(40, 80, 40), font=small,
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
