#!/usr/bin/env python3
"""K-scaling plot: bench score vs portfolio size K for greedy submodular.

Reads results/greedy_k{12,20,30,39}.json + results/ceiling_analysis_phase_o.json
and renders the cumulative-score curve. Marks each K we benched and
overlays the absolute ceiling. Makes the diminishing-returns shape
visually obvious.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/checkpoint15_k_scaling.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    # benched K results — Phase O (168 pool) and Phase P (207 pool)
    benched_o = []
    for k in (12, 20, 30, 39):
        p = Path(f"results/greedy_k{k}.json")
        if p.exists():
            j = json.loads(p.read_text())
            benched_o.append((j["k"], j["real_bench"]))
    benched_o.sort()
    benched_p = []
    for k in (20, 30, 44):
        p = Path(f"results/greedy_phase_p_k{k}.json")
        if p.exists():
            j = json.loads(p.read_text())
            benched_p.append((j["k"], j["real_bench"]))
    # also add Phase M K=12 = 49.79 and Phase P K=12 from ceiling analysis
    benched_p.insert(0, (12, 50.596))  # K=12 reading from Phase P ceiling
    benched_p.sort()

    # full greedy K-curve from latest (Phase P) ceiling analysis
    ceil_j = json.loads(Path("results/ceiling_analysis_phase_p.json").read_text())
    K_curve = [(k, s) for (k, s) in ceil_j["K_curve"]]
    ceiling = ceil_j["ceiling"]
    # keep variable name `benched` for downstream compatibility
    benched = benched_p

    W, H = 1400, 720
    img = Image.new("RGB", (W, H), (250, 250, 252))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=22)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=14)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=11)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    draw.text(
        (40, 18),
        f"Phase P — K-scaling on {ceil_j['n_candidates']}-candidate pool  (ceiling = {ceiling:.2f})",
        fill=(20, 20, 20), font=title_font,
    )

    # plot area
    px0, py0 = 80, 80
    px1, py1 = W - 320, H - 80

    draw.rectangle([px0, py0, px1, py1], outline=(180, 180, 180))

    max_K = K_curve[-1][0]
    max_y = ceiling * 1.05
    min_y = 25.0  # K=1 floor

    def xy(k, s):
        x = px0 + int(k / max_K * (px1 - px0))
        y = py1 - int((s - min_y) / (max_y - min_y) * (py1 - py0))
        return x, y

    # axis grid
    for tick in (30, 35, 40, 45, 50, 55):
        if tick > max_y:
            continue
        y = py1 - int((tick - min_y) / (max_y - min_y) * (py1 - py0))
        draw.line([(px0, y), (px1, y)], fill=(235, 235, 240), width=1)
        draw.text((px0 - 30, y - 6), f"{tick}",
                  fill=(120, 120, 120), font=small)
    for tick in (0, 10, 20, 30, 40, 50, max_K):
        if tick > max_K:
            continue
        x = px0 + int(tick / max_K * (px1 - px0))
        draw.text((x - 8, py1 + 6), f"K={tick}",
                  fill=(80, 80, 80), font=small)

    # full greedy curve
    pts = [xy(k, s) for (k, s) in K_curve]
    draw.polygon([(px0, py1)] + pts + [(px1, py1)],
                 fill=(235, 250, 240))
    draw.line(pts, fill=(50, 170, 90), width=3)

    # ceiling
    y_ceiling = py1 - int((ceiling - min_y) / (max_y - min_y) * (py1 - py0))
    draw.line([(px0, y_ceiling), (px1, y_ceiling)],
              fill=(200, 60, 60), width=2)
    draw.text((px0 + 10, y_ceiling - 16),
              f"absolute ceiling  {ceiling:.2f}",
              fill=(200, 60, 60), font=small)

    # benched K markers
    for (k, bench) in benched:
        x, y = xy(k, bench)
        draw.ellipse([x - 9, y - 9, x + 9, y + 9],
                     fill=(50, 170, 90), outline=(0, 80, 30), width=2)
        draw.text((x + 12, y - 18),
                  f"K={k}: {bench:.2f}",
                  fill=(20, 80, 40), font=font)
        # dropline
        draw.line([(x, y + 9), (x, py1)],
                  fill=(180, 200, 180), width=1)

    # right-side legend / readout
    lx = px1 + 30
    ly = py0 + 10
    draw.text((lx, ly), "Phase P.1 K-scaling result", fill=(20, 20, 20), font=font)
    ly += 28
    for (k, bench) in benched:
        marker = "  ⭐  " if k == max(b[0] for b in benched) else "      "
        draw.text((lx, ly), f"K={k:>2}    bench {bench:.2f}{marker}",
                  fill=(40, 40, 40), font=font)
        ly += 22
    ly += 8
    draw.text((lx, ly), "Marginal lift per +K:", fill=(40, 40, 40), font=font)
    ly += 22
    prev = None
    for (k, bench) in benched:
        if prev is None:
            draw.text((lx, ly), f"K={k}      baseline {bench:.2f}",
                      fill=(80, 80, 80), font=small)
        else:
            draw.text((lx, ly), f"K={prev[0]}→{k}   +{bench - prev[1]:.2f}",
                      fill=(80, 80, 80), font=small)
        ly += 16
        prev = (k, bench)

    ly += 16
    draw.text((lx, ly),
              "Reading: each K is greedy-submodular's best",
              fill=(40, 40, 40), font=small)
    ly += 14
    draw.text((lx, ly),
              "K-strategy portfolio. plan() runs all strategies",
              fill=(40, 40, 40), font=small)
    ly += 14
    draw.text((lx, ly),
              "per map and picks best — so larger K = better,",
              fill=(40, 40, 40), font=small)
    ly += 14
    draw.text((lx, ly),
              "at modest sim-time cost (~0.4s/strategy on 50 maps).",
              fill=(40, 40, 40), font=small)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
