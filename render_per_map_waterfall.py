#!/usr/bin/env python3
"""Per-map score waterfall with resource-bin coloring.

For each of the 50 bench maps, computes:
  - the SOTA portfolio's per-map best (what plan() actually picks)
  - the per-map oracle score (max across ALL 207 candidates — same as
    SOTA if the pool is saturated, but kept as a check)
  - the map's resource diversity bin (2 / 3 / 4 types)
  - the map's resource counts

Renders a waterfall (sorted ascending by SOTA score) where each bar is
colored by resource bin. Shows starkly: roughly half the maps are
resource-limited and contribute lower scores no matter what.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import factory_plan  # noqa: E402
from auto_factory import (  # noqa: E402
    build_from_spec, generate_map, score_plan, simulate,
)
from auto_factory.types import Resource  # noqa: E402
from factory_plan import _expand_strategy  # noqa: E402


SOURCE_RUNS = [
    "results/tournament_gpt55_xhigh.json",
    "results/tournament_gpt55_xhigh_rep2.json",
    "results/tournament_gpt54_seed400.json",
    "results/tournament_gpt54_seed600.json",
    "results/tournament_llm_seeded_6w.json",
    "results/tournament_anti_sota.json",
    "results/tournament_expanded_run1.json",
    "results/tournament_expanded_run2.json",
    "results/tournament_expanded_run3.json",
    "results/tournament_expanded_run4.json",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", type=int, default=50)
    ap.add_argument("--out", default="results/checkpoint16_per_map_waterfall.png")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    # collect all unique candidates
    all_strategies = []
    for f in SOURCE_RUNS:
        p = HERE / f
        if not p.exists():
            continue
        j = json.loads(p.read_text())
        for w in j.get("worker_results", []):
            for s in w.get("strategies", []):
                all_strategies.append(s)
        for s in j.get("merged_strategies", []):
            all_strategies.append(s)
    seen: set = set()
    candidates: list[dict] = []
    for s in all_strategies:
        k = tuple(sorted((kk, repr(v)) for kk, v in s.items()))
        if k not in seen:
            seen.add(k)
            candidates.append(s)
    print(f"  {len(candidates)} unique candidates")

    sota_strategies = factory_plan.CONFIG["strategies"]
    print(f"  SOTA K={len(sota_strategies)} strategies")

    rows = []
    for m in range(args.maps):
        gmap = generate_map(seed=m)
        rc = Counter(gmap.resources.values())
        types_present = sum(1 for r in Resource if rc.get(r, 0) > 0)
        total_res = sum(rc.get(r, 0) for r in Resource)

        # SOTA per-map best
        sota_best = float("-inf")
        sota_winner = -1
        for i, s in enumerate(sota_strategies):
            try:
                spec = _expand_strategy(s)
                plan = build_from_spec(gmap, spec)
                sim = simulate(plan, gmap, ticks=600)
                sc = score_plan(sim).total
                if sc > sota_best:
                    sota_best = sc
                    sota_winner = i
            except Exception:
                pass

        # oracle = best across all candidates
        oracle = float("-inf")
        for s in candidates:
            try:
                spec = _expand_strategy(s)
                plan = build_from_spec(gmap, spec)
                sim = simulate(plan, gmap, ticks=600)
                oracle = max(oracle, score_plan(sim).total)
            except Exception:
                pass

        rows.append({
            "map_seed": m,
            "sota_score": sota_best,
            "oracle_score": oracle,
            "types_present": types_present,
            "total_resources": total_res,
            "iron": rc.get(Resource.IRON, 0),
            "copper": rc.get(Resource.COPPER, 0),
            "coal": rc.get(Resource.COAL, 0),
            "oil": rc.get(Resource.OIL, 0),
            "sota_winner": sota_winner,
        })

    rows.sort(key=lambda r: r["sota_score"])

    # render
    W, H = 1500, 760
    img = Image.new("RGB", (W, H), (250, 250, 252))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=22)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=14)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=10)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    mean_score = sum(r["sota_score"] for r in rows) / len(rows)
    draw.text(
        (40, 18),
        f"Phase Q.1 — per-map SOTA waterfall  (K={len(sota_strategies)}, mean = {mean_score:.2f})",
        fill=(20, 20, 20), font=title_font,
    )
    draw.text(
        (40, 48),
        "sorted ascending by SOTA per-map score · bar height = score, color = resource diversity",
        fill=(80, 80, 80), font=small,
    )

    # plot area
    px0, py0 = 60, 90
    px1, py1 = W - 60, H - 200
    draw.rectangle([px0, py0, px1, py1], outline=(180, 180, 180))

    max_sc = max(r["sota_score"] for r in rows) * 1.1
    min_sc = 0
    span = max_sc - min_sc

    bar_w = (px1 - px0) // len(rows)

    for tick in (10, 20, 30, 40, 50, 60, 70):
        if tick > max_sc:
            continue
        y = py1 - int((tick - min_sc) / span * (py1 - py0))
        draw.line([(px0, y), (px1, y)], fill=(235, 235, 240), width=1)
        draw.text((px0 - 28, y - 6), f"{tick}", fill=(120, 120, 120), font=small)

    BIN_COLOR = {
        2: (200, 100, 100),   # red — only 2 resource types
        3: (200, 170, 70),    # amber — 3 types
        4: (60, 170, 90),     # green — full 4 types
    }
    for i, r in enumerate(rows):
        cx = px0 + i * bar_w
        bar_top = py1 - int((r["sota_score"] - min_sc) / span * (py1 - py0))
        color = BIN_COLOR.get(r["types_present"], (120, 120, 120))
        draw.rectangle(
            [cx + 1, bar_top, cx + bar_w - 2, py1 - 1],
            fill=color, outline=None,
        )
        # map seed label (vertical, sparse)
        if i % 3 == 0:
            draw.text((cx + 2, py1 + 4), f"{r['map_seed']}",
                      fill=(80, 80, 80), font=small)
        # score label on top for the bottom-5 + top-5
        if i < 5 or i >= len(rows) - 5:
            draw.text((cx, bar_top - 14),
                      f"{r['sota_score']:.1f}",
                      fill=(40, 40, 40), font=small)

    # mean line
    y_mean = py1 - int((mean_score - min_sc) / span * (py1 - py0))
    draw.line([(px0, y_mean), (px1, y_mean)],
              fill=(20, 80, 160), width=2)
    draw.text((px0 + 4, y_mean - 16),
              f"mean = {mean_score:.2f}",
              fill=(20, 80, 160), font=font)

    # legend
    legend_y = H - 170
    cats = [
        (2, "2 resource types (iron+copper only)"),
        (3, "3 resource types (missing oil or coal)"),
        (4, "4 resource types (full diversity)"),
    ]
    counts = Counter(r["types_present"] for r in rows)
    for j, (bin, label) in enumerate(cats):
        lx = 60 + j * 480
        draw.rectangle([lx, legend_y, lx + 16, legend_y + 16],
                       fill=BIN_COLOR[bin], outline=(0, 0, 0))
        draw.text((lx + 22, legend_y),
                  f"{label}",
                  fill=(40, 40, 40), font=font)
        n = counts.get(bin, 0)
        # avg score for this bin
        bin_rows = [r for r in rows if r["types_present"] == bin]
        avg = sum(r["sota_score"] for r in bin_rows) / max(1, len(bin_rows))
        draw.text((lx + 22, legend_y + 20),
                  f"{n} maps, avg score {avg:.2f}",
                  fill=(80, 80, 80), font=small)

    # summary footer
    fy = H - 115
    draw.text((60, fy),
              "Per-bin breakdown (sorted, lowest score per bin):",
              fill=(40, 40, 40), font=font)
    fy += 22
    for bin, _label in cats:
        bin_rows = sorted(
            [r for r in rows if r["types_present"] == bin],
            key=lambda r: r["sota_score"],
        )
        if not bin_rows:
            continue
        avg = sum(r["sota_score"] for r in bin_rows) / len(bin_rows)
        floor = min(r["sota_score"] for r in bin_rows)
        ceil = max(r["sota_score"] for r in bin_rows)
        draw.text(
            (60, fy),
            f"  {bin}-resource maps (N={len(bin_rows)}):  "
            f"min {floor:.2f},  mean {avg:.2f},  max {ceil:.2f}",
            fill=(40, 40, 40), font=small,
        )
        fy += 14

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
