#!/usr/bin/env python3
"""Ceiling + K-scaling analysis on the full candidate pool.

Loads results/greedy_submodular.json (which already has the 108 × 50
score matrix reconstructed below) and answers two questions:

  1) Absolute ceiling = mean of per-map max over all 108 candidates.
     This is the score a portfolio with infinite size could achieve.
  2) Cumulative greedy-submodular score vs K, for K = 1..N. Curve shows
     diminishing returns — where does the marginal gain go to zero?

Rebuilds the score matrix from candidates (same code path as
greedy_submodular.py — guaranteed identical numbers). Renders a
two-panel PNG.

Usage:
    python ceiling_analysis.py
    python ceiling_analysis.py --bench-maps 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import factory_plan  # noqa: E402
from auto_factory import build_from_spec, generate_map, score_plan, simulate  # noqa: E402


SOURCE_RUNS = [
    "results/tournament_gpt55_xhigh.json",
    "results/tournament_gpt55_xhigh_rep2.json",
    "results/tournament_gpt54_seed400.json",
    "results/tournament_gpt54_seed600.json",
    "results/tournament_llm_seeded_6w.json",
    "results/tournament_anti_sota.json",
    "results/tournament_expanded_run1.json",
    "results/tournament_expanded_run2.json",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-maps", type=int, default=50)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--out", default="results/checkpoint13_ceiling.png")
    ap.add_argument("--out-json", default="results/ceiling_analysis.json")
    return ap.parse_args()


def _signature(s: dict) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in s.items()))


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    # collect + dedup
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

    seen: set[tuple] = set()
    candidates: list[dict] = []
    for s in all_strategies:
        key = _signature(s)
        if key not in seen:
            seen.add(key)
            candidates.append(s)
    print(f"  {len(candidates)} unique candidates × {args.bench_maps} maps")

    # build score matrix
    print("  building score matrix…")
    score_matrix: list[list[float]] = []
    for ci, s in enumerate(candidates):
        spec = factory_plan._expand_strategy(s)
        row = []
        for m in range(args.bench_maps):
            gmap = generate_map(seed=args.seed_base + m)
            try:
                plan = build_from_spec(gmap, spec)
                sim = simulate(plan, gmap, ticks=600)
                row.append(score_plan(sim).total)
            except Exception:
                row.append(0.0)
        score_matrix.append(row)
        if (ci + 1) % 20 == 0 or ci == len(candidates) - 1:
            print(f"    [{ci + 1:>3}/{len(candidates)}]")

    # absolute ceiling
    per_map_max = [
        max(score_matrix[ci][m] for ci in range(len(candidates)))
        for m in range(args.bench_maps)
    ]
    ceiling = sum(per_map_max) / args.bench_maps
    print(f"\n  absolute ceiling (per-map max over all {len(candidates)} candidates): {ceiling:.3f}")

    # greedy submodular curve from K=1 to len(candidates)
    print("  computing greedy submodular curve K=1..N…")
    selected: list[int] = []
    best_per_map = [0.0] * args.bench_maps
    K_curve: list[tuple[int, float]] = []
    for step in range(len(candidates)):
        best_lift = -1.0
        best_idx = -1
        for ci in range(len(candidates)):
            if ci in selected:
                continue
            lift = 0.0
            for m in range(args.bench_maps):
                lift += max(score_matrix[ci][m], best_per_map[m]) - best_per_map[m]
            if lift > best_lift:
                best_lift = lift
                best_idx = ci
        if best_idx < 0 or best_lift <= 0:
            # remaining additions can only neutrally tie — stop
            break
        selected.append(best_idx)
        new_total = 0.0
        for m in range(args.bench_maps):
            best_per_map[m] = max(score_matrix[best_idx][m], best_per_map[m])
            new_total += best_per_map[m]
        K_curve.append((step + 1, new_total / args.bench_maps))

    print(f"  greedy submodular saturates at K={K_curve[-1][0]}  score={K_curve[-1][1]:.3f}")
    print(f"  current SOTA portfolio uses K=12  score={dict(K_curve).get(12, 0):.3f}")

    # render
    W, H = 1500, 720
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
        f"Phase N.1 — ceiling analysis  ({len(candidates)} candidates, {args.bench_maps} maps)",
        fill=(20, 20, 20), font=title_font,
    )

    # === LEFT: greedy submodular K-scaling curve ===
    cx0, cy0 = 80, 90
    cx1, cy1 = 720, 540
    draw.rectangle([cx0, cy0, cx1, cy1], outline=(180, 180, 180))
    draw.text((cx0, cy0 - 22),
              "Cumulative 50-map bench vs portfolio size K",
              fill=(40, 40, 40), font=font)

    max_K = K_curve[-1][0]
    max_sc = max(s for _k, s in K_curve)
    min_sc = 0.0
    span = max_sc - min_sc

    def cxy(k: int, s: float) -> tuple[int, int]:
        x = cx0 + int(k / max_K * (cx1 - cx0))
        y = cy1 - int((s - min_sc) / span * (cy1 - cy0))
        return x, y

    for tick in (0.25, 0.5, 0.75, 1.0):
        y = cy1 - int(tick * (cy1 - cy0))
        draw.line([(cx0, y), (cx1, y)], fill=(235, 235, 240), width=1)
        draw.text((cx0 - 30, y - 6), f"{tick * max_sc:.0f}", fill=(120, 120, 120), font=small)

    pts = [cxy(k, s) for (k, s) in K_curve]
    draw.line(pts, fill=(50, 170, 90), width=3)
    for (k, s) in K_curve:
        x, y = cxy(k, s)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(50, 170, 90))

    # mark K=12 (current SOTA)
    sota_k = 12
    sota_s = dict(K_curve).get(sota_k)
    if sota_s is not None:
        sx, sy = cxy(sota_k, sota_s)
        draw.line([(sx, sy + 4), (sx, cy1)], fill=(180, 100, 100), width=1)
        draw.ellipse([sx - 8, sy - 8, sx + 8, sy + 8],
                     outline=(180, 100, 100), width=2)
        draw.text((sx + 12, sy - 18),
                  f"current SOTA  K={sota_k}  {sota_s:.2f}",
                  fill=(180, 100, 100), font=small)

    # ceiling line
    cy_ceiling = cy1 - int((ceiling - min_sc) / span * (cy1 - cy0))
    draw.line([(cx0, cy_ceiling), (cx1, cy_ceiling)],
              fill=(200, 60, 60), width=2)
    draw.text((cx0 + 8, cy_ceiling + 4),
              f"absolute ceiling  {ceiling:.2f}  (per-map oracle over all {len(candidates)} candidates)",
              fill=(200, 60, 60), font=small)

    # x-axis labels
    for tick in (0, max_K // 4, max_K // 2, 3 * max_K // 4, max_K):
        x = cx0 + int(tick / max_K * (cx1 - cx0))
        draw.text((x - 6, cy1 + 4), f"K={tick}",
                  fill=(80, 80, 80), font=small)

    # === RIGHT: marginal lift per pick (diminishing returns) ===
    rx0, ry0 = 780, 90
    rx1, ry1 = W - 80, 540
    draw.rectangle([rx0, ry0, rx1, ry1], outline=(180, 180, 180))
    draw.text((rx0, ry0 - 22),
              "Marginal lift per added strategy (log-y diminishing returns)",
              fill=(40, 40, 40), font=font)

    # compute marginal lifts
    marginals = []
    prev = 0.0
    for (k, s) in K_curve:
        marginals.append((k, (s - prev) * args.bench_maps))
        prev = s
    # log-y axis
    import math
    max_m = max(m for _k, m in marginals)
    min_m = max(0.01, min(m for _k, m in marginals if m > 0))

    def rxy(k: int, m: float) -> tuple[int, int]:
        m = max(m, 0.001)
        x = rx0 + int(k / max_K * (rx1 - rx0))
        y = ry1 - int(
            (math.log10(m) - math.log10(min_m))
            / max(0.01, math.log10(max_m) - math.log10(min_m))
            * (ry1 - ry0)
        )
        return x, y

    for tick_log in (-1, 0, 1, 2, 3):
        v = 10 ** tick_log
        if v < min_m or v > max_m * 2:
            continue
        y = ry1 - int(
            (math.log10(v) - math.log10(min_m))
            / max(0.01, math.log10(max_m) - math.log10(min_m))
            * (ry1 - ry0)
        )
        draw.line([(rx0, y), (rx1, y)], fill=(235, 235, 240), width=1)
        draw.text((rx0 - 38, y - 6), f"{v:g}", fill=(120, 120, 120), font=small)

    pts2 = [rxy(k, m) for (k, m) in marginals]
    draw.line(pts2, fill=(60, 130, 200), width=2)
    for (k, m) in marginals:
        x, y = rxy(k, m)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(60, 130, 200))

    # === FOOTER: summary ===
    fy = 570
    headroom = ceiling - dict(K_curve).get(12, 0)
    pct = (headroom / ceiling) * 100 if ceiling > 0 else 0
    summary_lines = [
        f"Absolute ceiling (per-map oracle over {len(candidates)} candidates):  {ceiling:.3f}",
        f"Current SOTA at K=12:                                                  {dict(K_curve).get(12, 0):.3f}",
        f"Headroom inside this candidate pool:                                   {headroom:.3f}  ({pct:.1f}% of ceiling)",
        f"Greedy submodular saturates at K={K_curve[-1][0]} with score {K_curve[-1][1]:.3f}",
        f"   → past K={K_curve[-1][0]} the marginal lift goes ≤ 0 (no remaining candidate adds anything new).",
        f"Lesson: to push past {dict(K_curve).get(12, 0):.2f} we need NEW candidates, not bigger K.",
    ]
    for j, line in enumerate(summary_lines):
        draw.text((60, fy + j * 18), line,
                  fill=(40, 40, 40) if j == 0 else (60, 60, 60),
                  font=small if j > 0 else font)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")

    # also save JSON
    out_path = HERE / args.out_json
    out_path.write_text(json.dumps({
        "n_candidates": len(candidates),
        "bench_maps": args.bench_maps,
        "ceiling": ceiling,
        "sota_K12_score": dict(K_curve).get(12),
        "K_curve": K_curve,
        "marginal_lifts": marginals,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
