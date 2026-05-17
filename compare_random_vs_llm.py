#!/usr/bin/env python3
"""Overlay iterate.py (random) vs iterate_llm.py (LLM) convergence curves.

Reads results/iterate.jsonl and results/iterate_llm.jsonl, plots both
running-best lines against ATTEMPT NUMBER (not wall-clock — LLM is
~200x slower per attempt). Annotates accepts on each curve plus the
LLM's per-call latency.

Use this to ask: does the LLM converge in fewer attempts even though
each attempt costs more?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random-log", default="results/iterate.jsonl")
    ap.add_argument("--llm-log", default="results/iterate_llm.jsonl")
    ap.add_argument("--out", default="results/checkpoint7_random_vs_llm.png")
    return ap.parse_args()


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    rand_rows = [r for r in _load(Path(args.random_log)) if r.get("iter", -1) >= 0]
    llm_rows = [r for r in _load(Path(args.llm_log)) if r.get("iter", -1) >= 0]
    if not rand_rows and not llm_rows:
        print("no rows in either log")
        return 1

    n_rand = max((r["iter"] for r in rand_rows), default=0)
    n_llm = max((r["iter"] for r in llm_rows), default=0)
    n_max = max(n_rand, n_llm, 1)

    all_scores = [r["score"] for r in rand_rows + llm_rows] + [
        r["best"] for r in rand_rows + llm_rows
    ]
    lo = min(all_scores)
    hi = max(all_scores)
    span = max(1e-6, hi - lo)

    margin = 60
    W, H = 1200, 600
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
    px1, py1 = W - margin - 280, H - margin
    draw.rectangle([px0, py0, px1, py1], outline=(180, 180, 180))

    def xy(it: int, sc: float) -> tuple[int, int]:
        x = px0 + int((it / n_max) * (px1 - px0))
        y = py1 - int((sc - lo) / span * (py1 - py0))
        return x, y

    for frac in (0.25, 0.5, 0.75):
        gy = py1 - int(frac * (py1 - py0))
        draw.line([(px0, gy), (px1, gy)], fill=(235, 235, 240), width=1)
        val = lo + frac * span
        draw.text((px0 - 40, gy - 6), f"{val:.1f}", fill=(120, 120, 120), font=small)
    draw.text((px0 - 40, py0 - 8), f"{hi:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0 - 40, py1 - 6), f"{lo:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0, py1 + 6), "attempt 0", fill=(80, 80, 80), font=small)
    draw.text((px1 - 60, py1 + 6), f"attempt {n_max}", fill=(80, 80, 80), font=small)

    series = [
        ("random (iterate.py)", rand_rows, (180, 100, 100)),
        ("LLM (iterate_llm.py)", llm_rows, (60, 130, 200)),
    ]
    for name, rows, color in series:
        if not rows:
            continue
        for r in rows:
            x, y = xy(r["iter"], r["score"])
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)
        pts = [xy(r["iter"], r["best"]) for r in rows]
        if len(pts) > 1:
            draw.line(pts, fill=color, width=3)
        for r in rows:
            if r["accept"]:
                x, y = xy(r["iter"], r["score"])
                draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=color, width=2)

    draw.text(
        (margin, 16),
        "Random vs LLM-driven mutation — convergence by attempt number",
        fill=(20, 20, 20),
        font=title_font,
    )

    # legend / summary
    lx = px1 + 32
    ly = py0
    draw.text((lx, ly), "series  attempts / accepts / best", fill=(40, 40, 40), font=font)
    ry = ly + 28
    for name, rows, color in series:
        if not rows:
            continue
        accepts = sum(1 for r in rows if r["accept"])
        best = max(r["best"] for r in rows)
        draw.line([(lx, ry + 6), (lx + 16, ry + 6)], fill=color, width=3)
        draw.text(
            (lx + 22, ry),
            f"{name}",
            fill=color,
            font=font,
        )
        draw.text(
            (lx + 22, ry + 18),
            f"  {len(rows)} attempts / {accepts} acc / best {best:.2f}",
            fill=(60, 60, 60),
            font=small,
        )
        ry += 46

    # LLM-specific stats
    if llm_rows:
        llm_latencies = [r.get("llm_latency_sec") for r in llm_rows if r.get("llm_latency_sec")]
        if llm_latencies:
            avg = sum(llm_latencies) / len(llm_latencies)
            total = sum(llm_latencies)
            draw.text((lx, ry + 10), "LLM cost:", fill=(40, 40, 40), font=font)
            draw.text(
                (lx, ry + 28),
                f"  avg {avg:.1f}s/call, total {total:.0f}s",
                fill=(60, 60, 60),
                font=small,
            )
            n_fallback = sum(1 for r in llm_rows if "fallback" in r.get("source", ""))
            if n_fallback:
                draw.text(
                    (lx, ry + 44),
                    f"  fallback random: {n_fallback}/{len(llm_rows)}",
                    fill=(150, 60, 60),
                    font=small,
                )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
