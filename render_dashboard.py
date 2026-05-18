#!/usr/bin/env python3
"""Project dashboard — single-image state-of-the-art view.

Six panels in one PNG:
  1. SOTA arc over phases (50-map train bench)
  2. Train vs held-out generalization gap (50 vs 50 vs 100 map bench)
  3. Search space size growth by phase
  4. Ceiling vs SOTA growth by phase
  5. Per-bin SOTA breakdown (2-res / 3-res / 4-res) with overfit gap
  6. Lessons learned text panel

This is the "where are we?" snapshot after 18 phases (A → S).
"""

from __future__ import annotations

import argparse
from pathlib import Path


PHASE_SOTA = [
    # (label, train-bench, search-space-size, pool-size, ceiling)
    ("A v0",       7.0,    0,    0,    None),
    ("A v1",       18.6,   0,    0,    None),
    ("A v3",       26.8,   0,    0,    None),
    ("B random",   38.8,   11664, 0,    None),
    ("G tour",     43.2,   11664, 0,    None),
    ("L.1 5.5",    44.88,  11664, 88,   None),
    ("M.1' greedy", 49.79, 11664, 108,  50.73),
    ("O.3 K=39",   52.39,  64152, 168,  52.39),
    ("P.3 K=44",   53.19,  64152, 207,  53.19),
    ("R.4 K=45",   54.135, 64218, 247,  54.135),  # +2 patterns
    ("S.4 K=45",   54.152, 64218, 267,  54.152),  # adaptive lanes (neutral)
]

HELDOUT = {
    "train (0-49)":    54.152,
    "held-out (50-99)": 50.909,
    "combined (0-99)":  52.531,
}

PER_BIN = {
    "train": {2: (4, 40.66), 3: (25, 53.24), 4: (21, 57.81)},
    "heldout": {2: (3, 39.06), 3: (31, 50.52), 4: (16, 53.88)},
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/checkpoint19_dashboard.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1600, 1000
    img = Image.new("RGB", (W, H), (250, 250, 252))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=26)
        sub_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=16)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=12)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=10)
    except OSError:
        title_font = ImageFont.load_default()
        sub_font = title_font
        font = title_font
        small = title_font

    draw.text((40, 18), "Auto Factory — project dashboard (phases A → S)",
              fill=(20, 20, 20), font=title_font)
    draw.text((40, 52),
              f"in-sample SOTA: 54.15  ·  held-out SOTA: 50.91  ·  +670% over v0 naive",
              fill=(80, 80, 80), font=sub_font)

    # === PANEL 1: SOTA arc (top-left, large) ===
    p1 = (60, 110, 800, 470)
    draw.rectangle(p1, outline=(180, 180, 180))
    draw.text((p1[0], p1[1] - 22), "SOTA per phase (50-map train bench)",
              fill=(40, 40, 40), font=sub_font)

    max_s = 60.0
    min_s = 0.0
    n = len(PHASE_SOTA)
    dx = (p1[2] - p1[0] - 60) / max(1, n - 1)
    for tick in (10, 20, 30, 40, 50, 60):
        gy = p1[3] - int((tick - min_s) / (max_s - min_s) * (p1[3] - p1[1]))
        draw.line([(p1[0] + 40, gy), (p1[2], gy)], fill=(235, 235, 240), width=1)
        draw.text((p1[0] + 6, gy - 6), f"{tick}", fill=(120, 120, 120), font=small)
    # envelope (running max)
    pts = []
    running = float("-inf")
    for i, (lbl, sc, *_) in enumerate(PHASE_SOTA):
        running = max(running, sc)
        x = p1[0] + 40 + int(i * dx)
        y = p1[3] - int((running - min_s) / (max_s - min_s) * (p1[3] - p1[1]))
        pts.append((x, y))
    poly = [(p1[0] + 40, p1[3])] + pts + [(p1[2], p1[3])]
    draw.polygon(poly, fill=(235, 250, 240))
    draw.line(pts, fill=(50, 170, 90), width=2)
    # dots + labels
    for i, (lbl, sc, *_) in enumerate(PHASE_SOTA):
        x = p1[0] + 40 + int(i * dx)
        y = p1[3] - int((sc - min_s) / (max_s - min_s) * (p1[3] - p1[1]))
        kind = "sota" if i == len(PHASE_SOTA) - 1 else "phase"
        col = (50, 170, 90) if kind == "sota" else (60, 130, 200)
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=col, outline=(0, 0, 0))
        draw.text((x - 12, y - 18), f"{sc:.1f}", fill=(40, 40, 40), font=small)
        # rotated label below (vertical char stack)
        for j, ch in enumerate(lbl[:10]):
            draw.text((x - 4, p1[3] + 6 + j * 9), ch, fill=(80, 80, 80), font=small)

    # === PANEL 2: generalization gap (top-right) ===
    p2 = (840, 110, W - 40, 320)
    draw.rectangle(p2, outline=(180, 180, 180))
    draw.text((p2[0], p2[1] - 22), "Generalization: train vs held-out 50-map bench",
              fill=(40, 40, 40), font=sub_font)
    bar_w = (p2[2] - p2[0] - 80) // len(HELDOUT)
    max_v = max(HELDOUT.values()) * 1.1
    for i, (lbl, v) in enumerate(HELDOUT.items()):
        cx = p2[0] + 40 + i * bar_w
        cy_top = p2[3] - int(v / max_v * (p2[3] - p2[1] - 60))
        color = (50, 170, 90) if "held" in lbl else ((60, 130, 200) if "train" in lbl else (150, 100, 200))
        draw.rectangle([cx, cy_top, cx + bar_w - 20, p2[3] - 1],
                       fill=color, outline=(0, 0, 0))
        draw.text((cx, cy_top - 18), f"{v:.2f}", fill=(20, 20, 20), font=font)
        # label
        for j, line in enumerate(lbl.split(" ")):
            draw.text((cx, p2[3] + 4 + j * 14), line,
                      fill=(60, 60, 60), font=small)
    gap = HELDOUT["train (0-49)"] - HELDOUT["held-out (50-99)"]
    draw.text(
        (p2[0] + 20, p2[1] + 6),
        f"overfit gap: {gap:+.2f}  ({gap / HELDOUT['train (0-49)'] * 100:.1f}% drop on unseen maps)",
        fill=(200, 60, 60), font=font,
    )

    # === PANEL 3: search space / pool growth (middle-right) ===
    p3 = (840, 360, W - 40, 600)
    draw.rectangle(p3, outline=(180, 180, 180))
    draw.text((p3[0], p3[1] - 22), "Search space & candidate pool growth",
              fill=(40, 40, 40), font=sub_font)
    # show search space size (log scale) and pool size on twin y-axes
    space_max = max(s for _, _, s, _, _ in PHASE_SOTA) or 1
    pool_max = max(p for _, _, _, p, _ in PHASE_SOTA) or 1
    n3 = len(PHASE_SOTA)
    dx3 = (p3[2] - p3[0] - 60) / max(1, n3 - 1)
    for i, (lbl, sc, sp, po, _ce) in enumerate(PHASE_SOTA):
        x = p3[0] + 40 + int(i * dx3)
        # search space bar (left, blue)
        if sp:
            h_sp = int(sp / space_max * (p3[3] - p3[1] - 80))
            draw.rectangle([x - 10, p3[3] - h_sp, x - 2, p3[3] - 4],
                           fill=(60, 130, 200), outline=None)
        if po:
            h_po = int(po / pool_max * (p3[3] - p3[1] - 80))
            draw.rectangle([x + 2, p3[3] - h_po, x + 10, p3[3] - 4],
                           fill=(50, 170, 90), outline=None)
        for j, ch in enumerate(lbl[:7]):
            draw.text((x - 4, p3[3] + 6 + j * 9), ch,
                      fill=(80, 80, 80), font=small)
    # legend
    draw.rectangle([p3[0] + 10, p3[1] + 10, p3[0] + 22, p3[1] + 22],
                   fill=(60, 130, 200))
    draw.text((p3[0] + 28, p3[1] + 10),
              f"search-space size (max {space_max:,})",
              fill=(40, 40, 40), font=small)
    draw.rectangle([p3[0] + 10, p3[1] + 30, p3[0] + 22, p3[1] + 42],
                   fill=(50, 170, 90))
    draw.text((p3[0] + 28, p3[1] + 30),
              f"candidate pool size (max {pool_max})",
              fill=(40, 40, 40), font=small)

    # === PANEL 4: ceiling vs SOTA over phases (bottom-left) ===
    p4 = (60, 530, 800, 800)
    draw.rectangle(p4, outline=(180, 180, 180))
    draw.text((p4[0], p4[1] - 22),
              "SOTA vs absolute ceiling per phase  (gap = how much was left)",
              fill=(40, 40, 40), font=sub_font)
    n4 = len(PHASE_SOTA)
    dx4 = (p4[2] - p4[0] - 60) / max(1, n4 - 1)
    for tick in (40, 45, 50, 55):
        gy = p4[3] - int((tick - 35) / 25 * (p4[3] - p4[1] - 30))
        draw.line([(p4[0] + 40, gy), (p4[2], gy)],
                  fill=(235, 235, 240), width=1)
        draw.text((p4[0] + 6, gy - 6), f"{tick}",
                  fill=(120, 120, 120), font=small)
    for i, (lbl, sc, _sp, _po, ce) in enumerate(PHASE_SOTA):
        x = p4[0] + 40 + int(i * dx4)
        if sc > 35:
            y = p4[3] - int((sc - 35) / 25 * (p4[3] - p4[1] - 30))
            draw.ellipse([x - 5, y - 5, x + 5, y + 5],
                         fill=(50, 170, 90), outline=(0, 0, 0))
        if ce is not None and ce > 35:
            y_ce = p4[3] - int((ce - 35) / 25 * (p4[3] - p4[1] - 30))
            draw.ellipse([x - 5, y_ce - 5, x + 5, y_ce + 5],
                         fill=(255, 255, 255), outline=(200, 60, 60), width=2)
            # dropline showing gap
            if sc > 35:
                draw.line([(x, y_ce), (x, y)], fill=(200, 60, 60), width=1)
        for j, ch in enumerate(lbl[:7]):
            draw.text((x - 4, p4[3] + 6 + j * 9), ch,
                      fill=(80, 80, 80), font=small)
    draw.text((p4[0] + 10, p4[1] + 8),
              "green = SOTA (50-map train), red ring = absolute pool ceiling",
              fill=(40, 40, 40), font=small)

    # === PANEL 5: per-bin overfit (bottom-middle) ===
    p5 = (840, 640, 1220, 900)
    draw.rectangle(p5, outline=(180, 180, 180))
    draw.text((p5[0], p5[1] - 22), "Per-resource-bin SOTA: train vs held-out",
              fill=(40, 40, 40), font=sub_font)
    bin_max = 70.0
    for j, (label, color) in enumerate([("train", (60, 130, 200)),
                                         ("heldout", (50, 170, 90))]):
        for i, b in enumerate([2, 3, 4]):
            n, v = PER_BIN[label][b]
            cx = p5[0] + 40 + i * 100 + j * 40
            cy_top = p5[3] - int(v / bin_max * (p5[3] - p5[1] - 60))
            draw.rectangle([cx, cy_top, cx + 36, p5[3] - 1],
                           fill=color, outline=(0, 0, 0))
            draw.text((cx, cy_top - 14), f"{v:.1f}",
                      fill=(20, 20, 20), font=small)
    # bin labels
    for i, b in enumerate([2, 3, 4]):
        cx = p5[0] + 40 + i * 100 + 20
        draw.text((cx, p5[3] + 4), f"{b}-resource",
                  fill=(80, 80, 80), font=small)
    # legend
    draw.rectangle([p5[0] + 240, p5[1] + 10, p5[0] + 252, p5[1] + 22],
                   fill=(60, 130, 200))
    draw.text((p5[0] + 258, p5[1] + 10), "train", fill=(40, 40, 40), font=small)
    draw.rectangle([p5[0] + 240, p5[1] + 30, p5[0] + 252, p5[1] + 42],
                   fill=(50, 170, 90))
    draw.text((p5[0] + 258, p5[1] + 30), "held-out", fill=(40, 40, 40), font=small)

    # === PANEL 6: lessons learned text (right column) ===
    p6 = (1240, 640, W - 40, 920)
    draw.rectangle(p6, outline=(180, 180, 180))
    draw.text((p6[0], p6[1] - 22), "Lessons learned",
              fill=(40, 40, 40), font=sub_font)
    lessons = [
        "1. LLM ≈ random per wall-clock;",
        "   LLM wins per ATTEMPT (Phase H/I/J)",
        "2. Smart selection > stronger LLM",
        "   greedy submodular +4.9 (Phase M)",
        "3. Portfolio cap was free money",
        "   K=12→K=44 +2.95 (Phase P)",
        "4. Search-space expansion helps",
        "   ×5.5 combos → ceiling +1.6 (O)",
        "5. Adaptive_resource at right",
        "   abstraction layer: +0.94 (R)",
        "6. Adaptive_lanes wrong layer:",
        "   neutral (S, negative result)",
        "7. ~6% in-sample overfit on the",
        "   50-map training bench (T)",
    ]
    for i, line in enumerate(lessons):
        draw.text((p6[0] + 10, p6[1] + 10 + i * 18), line,
                  fill=(40, 40, 40), font=small)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
