#!/usr/bin/env python3
"""4-way bench summary: random vs LLM vs hybrid vs LLM-seeded tournament.

Phase J's tournament has a different shape (4 parallel workers, no single
convergence curve), so this plot uses BAR-CHART + per-worker dots for the
tournament, plus the running-best curves for the three sequential
methods. Reads results/iterate.jsonl, results/iterate_llm.jsonl,
results/iterate_hybrid.jsonl, and results/tournament_llm_seeded.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/checkpoint9_four_way.png")
    return ap.parse_args()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _running_best(rows: list[dict]) -> list[tuple[int, float]]:
    out = []
    best = float("-inf")
    attempt = 0
    for r in rows:
        if r.get("iter", 0) < 0 or "score" not in r:
            continue
        if r.get("source") == "basin_proposal":
            continue
        attempt += 1
        s = float(r["score"])
        if s > best:
            best = s
        out.append((attempt, best))
    return out


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    rand = _running_best(_load_jsonl(Path("results/iterate.jsonl")))
    llm = _running_best(_load_jsonl(Path("results/iterate_llm.jsonl")))
    hyb = _running_best(_load_jsonl(Path("results/iterate_hybrid.jsonl")))

    seeded_json = Path("results/tournament_llm_seeded.json")
    seeded = json.loads(seeded_json.read_text()) if seeded_json.exists() else None

    # bench numbers for the bar chart
    bench_rows = [
        ("Random\n(Phase B/D)", max((b for _a, b in rand), default=0), (180, 100, 100), 38.79),
        ("LLM-only\n(Phase H)", max((b for _a, b in llm), default=0), (60, 130, 200), 30.51),
        ("Hybrid LLM-meta\n(Phase I)", max((b for _a, b in hyb), default=0), (40, 160, 90), 36.06),
        ("LLM-seeded tournament\n(Phase J)",
         seeded["merged_bench_score"] if seeded else 0, (155, 100, 200),
         seeded["merged_bench_score"] if seeded else 0),
    ]

    W, H = 1400, 720
    img = Image.new("RGB", (W, H), (252, 252, 252))
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
        "Phase J — 4-way comparison: 50-map bench scores across approaches",
        fill=(20, 20, 20), font=title_font,
    )

    # === LEFT: bar chart of 50-map bench scores ===
    bx0, by0 = 80, 100
    bx1, by1 = 640, 540
    draw.rectangle([bx0, by0, bx1, by1], outline=(180, 180, 180))

    all_vals = [r[3] for r in bench_rows] + [r[1] for r in bench_rows]
    hi = max(all_vals) * 1.1
    bar_w = (bx1 - bx0 - 80) // len(bench_rows)
    for i, (name, _curve_best, color, bench) in enumerate(bench_rows):
        cx = bx0 + 40 + i * bar_w
        cy_top = by1 - int((bench / hi) * (by1 - by0))
        draw.rectangle(
            [cx, cy_top, cx + bar_w - 24, by1 - 1],
            fill=color, outline=(0, 0, 0),
        )
        draw.text(
            (cx, cy_top - 22),
            f"{bench:.2f}",
            fill=(20, 20, 20), font=font,
        )
        for j, line in enumerate(name.split("\n")):
            draw.text((cx, by1 + 8 + j * 14), line, fill=(60, 60, 60), font=small)

    for frac in (0.25, 0.5, 0.75, 1.0):
        gy = by1 - int(frac * (by1 - by0))
        draw.line([(bx0, gy), (bx1, gy)], fill=(235, 235, 240), width=1)
        draw.text(
            (bx0 - 30, gy - 6),
            f"{frac * hi:.0f}",
            fill=(120, 120, 120), font=small,
        )
    draw.text((bx0, by0 - 22), "50-map mean bench score (higher = better)",
              fill=(40, 40, 40), font=font)

    # === RIGHT: running-best curves for sequential methods ===
    cx0, cy0 = 720, 100
    cx1, cy1 = W - 80, 540
    draw.rectangle([cx0, cy0, cx1, cy1], outline=(180, 180, 180))
    draw.text((cx0, cy0 - 22), "Running-best by ATTEMPT (sequential methods)",
              fill=(40, 40, 40), font=font)

    max_att = max(
        (rand[-1][0] if rand else 0),
        (llm[-1][0] if llm else 0),
        (hyb[-1][0] if hyb else 0),
        1,
    )
    all_scores: list[float] = []
    for curve in (rand, llm, hyb):
        all_scores.extend(b for _a, b in curve)
    if seeded:
        all_scores.append(seeded["merged_bench_score"])
    lo, hi2 = min(all_scores), max(all_scores)
    span = max(1e-6, hi2 - lo)

    def cxy(a: int, s: float) -> tuple[int, int]:
        x = cx0 + int(a / max_att * (cx1 - cx0))
        y = cy1 - int((s - lo) / span * (cy1 - cy0))
        return x, y

    for frac in (0.25, 0.5, 0.75):
        gy = cy1 - int(frac * (cy1 - cy0))
        draw.line([(cx0, gy), (cx1, gy)], fill=(235, 235, 240), width=1)
        val = lo + frac * span
        draw.text((cx0 - 38, gy - 6), f"{val:.1f}",
                  fill=(120, 120, 120), font=small)

    for (name, curve, color, _bench) in [
        ("random", rand, (180, 100, 100), None),
        ("LLM-only", llm, (60, 130, 200), None),
        ("hybrid", hyb, (40, 160, 90), None),
    ]:
        if len(curve) > 1:
            pts = [cxy(a, b) for (a, b) in curve]
            draw.line(pts, fill=color, width=3)

    # tournament: show as horizontal line at its bench score
    if seeded:
        bench = seeded["merged_bench_score"]
        y = cy1 - int((bench - lo) / span * (cy1 - cy0))
        draw.line([(cx0, y), (cx1, y)], fill=(155, 100, 200), width=3)
        draw.text(
            (cx1 - 200, y - 14),
            f"LLM-seeded tournament: {bench:.2f}",
            fill=(155, 100, 200), font=small,
        )
        # also plot the 4 individual worker scores as dots near right edge
        for w in seeded["worker_results"]:
            ws = w["score"]
            wy = cy1 - int((ws - lo) / span * (cy1 - cy0))
            wx = cx1 - 30
            draw.ellipse(
                [wx - 4, wy - 4, wx + 4, wy + 4],
                fill=(155, 100, 200), outline=(80, 50, 120),
            )

    # legend
    lx, ly = cx0 + 10, cy0 + 10
    draw.text((lx, ly), "methods:", fill=(40, 40, 40), font=font)
    ly += 22
    for (name, color) in [
        ("random walk", (180, 100, 100)),
        ("LLM-only", (60, 130, 200)),
        ("hybrid (LLM-meta + random)", (40, 160, 90)),
        ("LLM-seeded tournament (4 parallel)", (155, 100, 200)),
    ]:
        draw.line([(lx, ly + 6), (lx + 16, ly + 6)], fill=color, width=3)
        draw.text((lx + 22, ly), name, fill=color, font=small)
        ly += 18

    # === FOOTER: per-method summary table ===
    fy = 580
    draw.text((40, fy), "Recipe summary:", fill=(40, 40, 40), font=font)
    fy += 24
    rows = [
        ("Phase B/D random",      "93 sequential attempts",   "150 ms/atttempt", "→ 38.79"),
        ("Phase H LLM-only",      "12 sequential attempts",   "53 s/attempt",    "→ 30.51"),
        ("Phase I hybrid",        "10 basins × 15 inner",     "LLM-meta + rand", "→ 36.06"),
        ("Phase J LLM-seeded",    "1 LLM call → 4 parallel",  "46 s + 95 s",     f"→ {seeded['merged_bench_score']:.2f}" if seeded else "→ ?"),
    ]
    for (m, shape, cost, bench) in rows:
        draw.text((60, fy), m, fill=(40, 40, 40), font=small)
        draw.text((280, fy), shape, fill=(60, 60, 60), font=small)
        draw.text((520, fy), cost, fill=(60, 60, 60), font=small)
        draw.text((720, fy), bench, fill=(40, 40, 40), font=small)
        fy += 18

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
