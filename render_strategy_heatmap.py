#!/usr/bin/env python3
"""Per-map strategy-winner heat map for the current factory_plan.py SOTA.

Runs the 12-strategy portfolio on 50 deterministic maps. For each map,
records which strategy won (highest internal score). Then renders:

  1) Strategy-winner bar chart — how often each strategy wins.
  2) Per-map scoreboard — small color-coded grid showing which strategy
     won each map, with the map's resource-mix highlighted as a stripe.

Answers the question: "is the portfolio actually a mixture-of-experts,
or are 2 strategies winning everything and the other 10 are dead weight?"

Usage:
    python render_strategy_heatmap.py
    python render_strategy_heatmap.py --maps 50 --seed-base 0
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import factory_plan  # noqa: E402
from factory_plan import _expand_strategy  # noqa: E402
from auto_factory import (  # noqa: E402
    GameMap, build_from_spec, generate_map, score_plan, simulate,
)
from auto_factory.types import Resource  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--out", default="results/checkpoint11_strategy_heatmap.png")
    return ap.parse_args()


def _strategy_label(s: dict, idx: int) -> str:
    return (
        f"S{idx}: {s['lane_y_set'].replace('y_', '')}/"
        f"{s['asm_x_pattern'].replace('stagger', 'st')}/"
        f"sm{s['smelter_offset']}/{s['miner_pick'].replace('closest_y','cy').replace('leftmost','lm').replace('min_route','mr')}"
    )


def _resource_mix(gmap: GameMap) -> dict[Resource, int]:
    """Count of each resource type present on this map."""
    c = Counter(gmap.resources.values())
    return {r: c.get(r, 0) for r in Resource}


def _score_strategy_on_map(strategy_spec: dict, gmap: GameMap) -> float:
    plan = build_from_spec(gmap, strategy_spec)
    sim = simulate(plan, gmap, ticks=600)
    return score_plan(sim).total


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    strategies = factory_plan.CONFIG["strategies"]
    print(f"  portfolio: {len(strategies)} strategies, running on {args.maps} maps…")

    # for each map, record (winner_idx, winner_score, per_strategy_score, resource_mix)
    results = []
    for m in range(args.maps):
        gmap = generate_map(seed=args.seed_base + m)
        per_strat_scores = []
        for s in strategies:
            spec = _expand_strategy(s)
            try:
                sc = _score_strategy_on_map(spec, gmap)
            except Exception:
                sc = float("-inf")
            per_strat_scores.append(sc)
        winner_idx = max(range(len(strategies)), key=lambda i: per_strat_scores[i])
        results.append({
            "map_seed": args.seed_base + m,
            "winner_idx": winner_idx,
            "winner_score": per_strat_scores[winner_idx],
            "per_strat": per_strat_scores,
            "resources": _resource_mix(gmap),
        })

    # === Render ===
    margin = 50
    W, H = 1500, 760
    img = Image.new("RGB", (W, H), (250, 250, 252))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=22)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=13)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=10)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    draw.text(
        (margin, 18),
        f"Phase L.3 — per-map winner analysis  ({len(strategies)} strategies × {args.maps} maps)",
        fill=(20, 20, 20), font=title_font,
    )

    # palette for strategies
    strat_palette = [
        (218, 80, 80),  (60, 130, 200), (40, 160, 90),  (155, 100, 200),
        (240, 160, 40), (90, 80, 160),  (200, 80, 130), (60, 160, 160),
        (170, 130, 60), (110, 170, 60), (200, 200, 60), (130, 130, 130),
    ]

    # === PANEL A: winner bar chart ===
    bx0, by0, bx1, by1 = margin, 70, 600, 380
    draw.text((bx0, by0 - 24), "How often each strategy wins:",
              fill=(40, 40, 40), font=font)
    draw.rectangle([bx0, by0, bx1, by1], outline=(180, 180, 180))

    wins = Counter(r["winner_idx"] for r in results)
    max_wins = max(wins.values()) if wins else 1
    bar_h = (by1 - by0 - 30) // max(1, len(strategies))
    for i, s in enumerate(strategies):
        n = wins.get(i, 0)
        color = strat_palette[i % len(strat_palette)]
        y0 = by0 + 10 + i * bar_h
        bar_len = int(n / max_wins * (bx1 - bx0 - 220))
        draw.rectangle([bx0 + 130, y0, bx0 + 130 + bar_len, y0 + bar_h - 4],
                       fill=color, outline=(0, 0, 0))
        draw.text((bx0 + 4, y0 + 1), _strategy_label(s, i), fill=(40, 40, 40), font=small)
        draw.text((bx0 + 130 + bar_len + 4, y0 + 1),
                  f"{n}/{args.maps} ({n/args.maps*100:.0f}%)",
                  fill=(40, 40, 40), font=small)

    # === PANEL B: per-map winner scoreboard ===
    sbx0, sby0 = 640, 70
    sbx1, sby1 = W - margin, 380
    draw.text((sbx0, sby0 - 24),
              "Per-map winners (rows = strategy index, columns = map seed):",
              fill=(40, 40, 40), font=font)
    cell_w = (sbx1 - sbx0) // args.maps
    cell_h = (sby1 - sby0) // len(strategies)
    for mi, r in enumerate(results):
        for si in range(len(strategies)):
            cx = sbx0 + mi * cell_w
            cy = sby0 + si * cell_h
            if si == r["winner_idx"]:
                color = strat_palette[si % len(strat_palette)]
                draw.rectangle(
                    [cx, cy, cx + cell_w - 1, cy + cell_h - 1],
                    fill=color, outline=(0, 0, 0),
                )
            else:
                # mark relative score
                rel = (r["per_strat"][si] - min(r["per_strat"])) / max(
                    1e-6, (r["winner_score"] - min(r["per_strat"]))
                )
                shade = int(220 - rel * 60)
                draw.rectangle(
                    [cx, cy, cx + cell_w - 1, cy + cell_h - 1],
                    fill=(shade, shade, shade + 4),
                    outline=(235, 235, 235),
                )
    # x-axis labels
    for tick in range(0, args.maps + 1, 10):
        draw.text((sbx0 + tick * cell_w - 6, sby1 + 4),
                  f"{tick}", fill=(80, 80, 80), font=small)

    # === PANEL C: resource-mix stripes ===
    rx0, ry0 = margin, 430
    rx1, ry1 = W - margin, 510
    draw.text((rx0, ry0 - 22),
              "Map resource mix — bottom stripe under each map seed (top→bottom: IRON/COPPER/COAL/OIL count):",
              fill=(40, 40, 40), font=font)
    RES_COLOR = {
        Resource.IRON:   (180, 80, 80),
        Resource.COPPER: (220, 130, 50),
        Resource.COAL:   (70, 70, 80),
        Resource.OIL:    (60, 90, 200),
    }
    max_count = max(
        sum(r["resources"].values()) for r in results
    )
    for mi, r in enumerate(results):
        cx = sbx0 + mi * cell_w
        total = sum(r["resources"].values()) or 1
        y_cursor = ry0
        h_total = (ry1 - ry0)
        for res in Resource:
            cnt = r["resources"].get(res, 0)
            h = int(cnt / total * h_total)
            if h > 0:
                draw.rectangle(
                    [cx, y_cursor, cx + cell_w - 1, y_cursor + h],
                    fill=RES_COLOR[res], outline=None,
                )
            y_cursor += h

    # also draw the strategy-color legend below
    legend_y = ry1 + 20
    draw.text((margin, legend_y - 20),
              "Strategy color legend (top-N winners highlighted):",
              fill=(40, 40, 40), font=font)
    for i, s in enumerate(strategies):
        col_x = margin + (i % 6) * 230
        col_y = legend_y + (i // 6) * 28
        draw.rectangle(
            [col_x, col_y, col_x + 14, col_y + 14],
            fill=strat_palette[i % len(strat_palette)], outline=(0, 0, 0),
        )
        draw.text(
            (col_x + 20, col_y),
            f"S{i}  ({wins.get(i, 0)} wins)",
            fill=(40, 40, 40), font=small,
        )
        draw.text(
            (col_x + 20, col_y + 12),
            _strategy_label(s, i),
            fill=(80, 80, 80), font=small,
        )

    # summary footer
    dead = sum(1 for i in range(len(strategies)) if wins.get(i, 0) == 0)
    top_share = max(wins.values()) / args.maps * 100 if wins else 0
    summary = (
        f"Active strategies: {len(strategies) - dead}/{len(strategies)}    "
        f"Top-strategy win share: {top_share:.0f}%    "
        f"Maps where a single 'dominant' strategy won (≥1 in 3 maps): "
        f"{sum(1 for c in wins.values() if c >= args.maps // 3)}"
    )
    draw.text((margin, H - 28), summary, fill=(40, 40, 40), font=font)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
