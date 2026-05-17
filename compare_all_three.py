#!/usr/bin/env python3
"""3-way convergence overlay: random vs LLM vs hybrid (LLM-meta + random-inner).

Reads results/iterate.jsonl (random), results/iterate_llm.jsonl (Phase H),
results/iterate_hybrid.jsonl (Phase I). Plots all three running-best lines
against ATTEMPT NUMBER on the left panel; against WALL-CLOCK on the right
panel (so we can see the random's throughput advantage explicitly).

Each method's per-attempt accept dots are colored faintly; the running-best
line is the bold trace.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random-log", default="results/iterate.jsonl")
    ap.add_argument("--llm-log", default="results/iterate_llm.jsonl")
    ap.add_argument("--hybrid-log", default="results/iterate_hybrid.jsonl")
    ap.add_argument("--out", default="results/checkpoint8_three_way.png")
    return ap.parse_args()


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _extract_curve(rows: list[dict], best_key: str) -> list[tuple[int, float, float, bool]]:
    """Return list of (attempt_idx, score, running_best, accept) in order.
    Skips header/footer sentinel rows (iter < 0 or no score)."""
    out = []
    attempt = 0
    running_best = float("-inf")
    for r in rows:
        # skip sentinels
        if r.get("iter", 0) < 0:
            continue
        if "score" not in r:
            continue
        # skip baseline-marker rows that weren't actual attempts
        if r.get("source") == "basin_proposal":
            continue
        score = r["score"]
        # for hybrid log, prefer the row's own best_in_basin; otherwise compute
        if best_key in r:
            rb = r[best_key]
        else:
            rb = max(running_best, score) if running_best != float("-inf") else score
        if rb > running_best:
            running_best = rb
        attempt += 1
        out.append((attempt, score, running_best, bool(r.get("accept"))))
    return out


def _extract_wallclock(rows: list[dict]) -> list[tuple[float, float, bool]]:
    """For wall-clock x-axis, use elapsed_sec if present.
    Returns (elapsed_sec, running_best, accept)."""
    out = []
    running_best = float("-inf")
    for r in rows:
        if r.get("iter", 0) < 0:
            continue
        if "score" not in r:
            continue
        if r.get("source") == "basin_proposal":
            continue
        score = r["score"]
        if score > running_best:
            running_best = score
        elapsed = r.get("elapsed_sec")
        if elapsed is None:
            continue
        out.append((float(elapsed), running_best, bool(r.get("accept"))))
    return out


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    rand = _load(Path(args.random_log))
    llm = _load(Path(args.llm_log))
    hyb = _load(Path(args.hybrid_log))

    rand_curve = _extract_curve(rand, best_key="best")
    llm_curve = _extract_curve(llm, best_key="best")
    # hybrid log stores per-basin best in `best_in_basin`; we compute global running best
    # ourselves by tracking max across all rows.
    hyb_curve_raw = _extract_curve(hyb, best_key="__none__")
    # recompute running_best as max-over-time
    rb = float("-inf")
    hyb_curve = []
    for (a, s, _ignore, acc) in hyb_curve_raw:
        if s > rb:
            rb = s
        hyb_curve.append((a, s, rb, acc))

    if not (rand_curve or llm_curve or hyb_curve):
        print("no rows in any log")
        return 1

    all_scores: list[float] = []
    for curve in (rand_curve, llm_curve, hyb_curve):
        for (_a, s, b, _acc) in curve:
            all_scores.extend([s, b])
    lo = min(all_scores)
    hi = max(all_scores)
    span = max(1e-6, hi - lo)
    max_attempts = max(
        (rand_curve[-1][0] if rand_curve else 0),
        (llm_curve[-1][0] if llm_curve else 0),
        (hyb_curve[-1][0] if hyb_curve else 0),
        1,
    )

    margin = 60
    W, H = 1400, 620
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

    # left panel: attempt-number axis
    px0L, py0 = margin, margin + 40
    px1L, py1 = W // 2 - 30, H - margin
    # right panel: wall-clock axis
    px0R, px1R = W // 2 + 30, W - margin - 220

    for box in ((px0L, py0, px1L, py1), (px0R, py0, px1R, py1)):
        draw.rectangle(list(box), outline=(180, 180, 180))

    def xy_attempt(it: int, sc: float) -> tuple[int, int]:
        x = px0L + int((it / max_attempts) * (px1L - px0L))
        y = py1 - int((sc - lo) / span * (py1 - py0))
        return x, y

    # determine wall-clock range
    rand_wc = _extract_wallclock(rand)
    llm_wc = _extract_wallclock(llm)
    hyb_wc = [(_a, b, acc) for (_a, _s, b, acc) in hyb_curve]  # hybrid lacks elapsed; use attempt as proxy
    # For wall-clock, use elapsed_sec where available; if a log lacks it, fall back to attempt * avg-per-attempt
    rand_max_wc = rand_wc[-1][0] if rand_wc else 0
    llm_max_wc = llm_wc[-1][0] if llm_wc else 0
    # hybrid: rough estimate — basin_proposal rows have llm_latency_sec
    hyb_wc_real: list[tuple[float, float, bool]] = []
    running_t = 0.0
    running_best = float("-inf")
    for r in hyb:
        if r.get("kind") == "basin_proposal":
            running_t += float(r.get("llm_latency_sec") or 0.0)
            continue
        if r.get("iter", 0) < 0:
            continue
        if "score" not in r:
            continue
        # treat each inner attempt as ~150ms (matches eval cost at 20 maps)
        running_t += 0.15
        s = r["score"]
        if s > running_best:
            running_best = s
        hyb_wc_real.append((running_t, running_best, bool(r.get("accept"))))
    hyb_max_wc = hyb_wc_real[-1][0] if hyb_wc_real else 0
    max_wc = max(rand_max_wc, llm_max_wc, hyb_max_wc, 1.0)

    def xy_wallclock(t: float, sc: float) -> tuple[int, int]:
        x = px0R + int((t / max_wc) * (px1R - px0R))
        y = py1 - int((sc - lo) / span * (py1 - py0))
        return x, y

    # grid lines + y labels (both panels)
    for frac in (0.25, 0.5, 0.75):
        gy = py1 - int(frac * (py1 - py0))
        for x0, x1 in ((px0L, px1L), (px0R, px1R)):
            draw.line([(x0, gy), (x1, gy)], fill=(235, 235, 240), width=1)
        val = lo + frac * span
        draw.text((px0L - 40, gy - 6), f"{val:.1f}", fill=(120, 120, 120), font=small)
    draw.text((px0L - 40, py0 - 8), f"{hi:.1f}", fill=(80, 80, 80), font=small)
    draw.text((px0L - 40, py1 - 6), f"{lo:.1f}", fill=(80, 80, 80), font=small)

    # x-axis labels
    draw.text((px0L, py1 + 6), "attempt 0", fill=(80, 80, 80), font=small)
    draw.text((px1L - 80, py1 + 6), f"attempt {max_attempts}", fill=(80, 80, 80), font=small)
    draw.text((px0R, py1 + 6), "wall-clock 0s", fill=(80, 80, 80), font=small)
    draw.text((px1R - 90, py1 + 6), f"{max_wc:.0f}s", fill=(80, 80, 80), font=small)

    # panel titles
    draw.text((px0L, py0 - 22),
              "Convergence by ATTEMPT number — LLM gets fewer rolls",
              fill=(40, 40, 40), font=font)
    draw.text((px0R, py0 - 22),
              "Convergence by WALL-CLOCK — random's throughput shows",
              fill=(40, 40, 40), font=font)

    series = [
        ("random (iterate.py)", rand_curve, rand_wc, (180, 100, 100)),
        ("LLM-only (Phase H)", llm_curve, llm_wc, (60, 130, 200)),
        ("Hybrid LLM-meta + random (Phase I)", hyb_curve, hyb_wc_real, (40, 160, 90)),
    ]
    for (name, curve_att, curve_wc, color) in series:
        # left panel — attempt axis
        if curve_att:
            for (a, s, _b, acc) in curve_att:
                x, y = xy_attempt(a, s)
                if acc:
                    draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color)
                else:
                    draw.ellipse([x - 2, y - 2, x + 2, y + 2], outline=color, width=1)
            pts = [xy_attempt(a, b) for (a, _s, b, _acc) in curve_att]
            if len(pts) > 1:
                draw.line(pts, fill=color, width=3)
        # right panel — wall-clock axis
        if curve_wc:
            pts = [xy_wallclock(t, b) for (t, b, _acc) in curve_wc]
            if len(pts) > 1:
                draw.line(pts, fill=color, width=3)
            for (t, b, acc) in curve_wc:
                if acc:
                    x, y = xy_wallclock(t, b)
                    draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)

    draw.text((margin, 16),
              "Phase I — Random vs LLM vs Hybrid LLM-meta + random-inner",
              fill=(20, 20, 20), font=title_font)

    # legend / summary on the right
    lx = px1R + 20
    ly = py0
    draw.text((lx, ly), "method   attempts / accepts / best", fill=(40, 40, 40), font=font)
    ry = ly + 28
    for (name, curve_att, curve_wc, color) in series:
        if not curve_att:
            continue
        accepts = sum(1 for (_a, _s, _b, acc) in curve_att if acc)
        best = max(b for (_a, _s, b, _acc) in curve_att)
        draw.line([(lx, ry + 6), (lx + 16, ry + 6)], fill=color, width=3)
        draw.text((lx + 22, ry), name, fill=color, font=font)
        draw.text(
            (lx + 22, ry + 18),
            f"  {len(curve_att)} attempts / {accepts} acc / best {best:.2f}",
            fill=(60, 60, 60),
            font=small,
        )
        rate = accepts / max(1, len(curve_att)) * 100
        draw.text(
            (lx + 22, ry + 32),
            f"  per-attempt accept: {rate:.0f}%",
            fill=(60, 60, 60),
            font=small,
        )
        ry += 58

    # interpretation footer
    foot = (
        "Reading: left = same attempt count, who climbs higher per roll?  "
        "right = same wall-clock, who actually wins given LLM's ~350x slowdown?"
    )
    draw.text((margin, H - 22), foot, fill=(80, 80, 80), font=small)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
