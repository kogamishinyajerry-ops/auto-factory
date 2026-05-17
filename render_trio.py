#!/usr/bin/env python3
"""Side-by-side trio evolution GIF: random / LLM / hybrid evolving in lockstep.

Each panel is a fixed-seed map showing that method's running-best plan
at a normalized timeline position. We align by FRACTION of total
best-updates, so a method with 16 best-updates and one with 7 are
shown at the "same" t when each is N% through its own evolution.

Top of canvas: score panel (running-best curve, all three on shared axes).
Below: three factory-grid panels side by side.

Usage:
    python render_trio.py
    python render_trio.py --seed 11 --cell-px 22
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import factory_plan  # noqa: E402
from auto_factory import generate_map, simulate, score_plan  # noqa: E402
from auto_factory.viz import _bld_map  # noqa: E402
from auto_factory.types import BuildingType  # noqa: E402


METHODS = [
    ("Random (Phase B/D)", "results/iterate.jsonl", (180, 100, 100)),
    ("LLM-only (Phase H)", "results/iterate_llm.jsonl", (60, 130, 200)),
    ("Hybrid (Phase I)", "results/iterate_hybrid.jsonl", (40, 160, 90)),
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/trio_evolution.gif")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cell-px", type=int, default=20)
    ap.add_argument("--n-frames", type=int, default=24,
                    help="frames in output GIF; each method is sampled at N evenly-spaced fractions")
    ap.add_argument("--frame-ms", type=int, default=600)
    return ap.parse_args()


def _load_best_updates(log: Path) -> list[dict]:
    out = []
    cur_best = float("-inf")
    for line in log.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("iter", 0) < 0 or "score" not in r or "cfg" not in r:
            continue
        if r.get("source") == "basin_proposal":
            continue
        s = float(r["score"])
        if s > cur_best:
            cur_best = s
            out.append({"score": s, "cfg": r["cfg"]})
    return out


def _sample_at_fractions(updates: list[dict], n: int) -> list[dict]:
    """Pick n best-updates at evenly spaced fractions [0..1]. Returns list
    of length n (the same update may repeat when the source list is short)."""
    if not updates:
        return []
    out = []
    for i in range(n):
        frac = i / max(1, n - 1)
        idx = int(round(frac * (len(updates) - 1)))
        out.append(updates[idx])
    return out


def _render_factory_panel(
    draw, base_x, base_y, gmap, plan, cell_px, panel_w
):
    """Draw one factory-grid panel onto an existing PIL image via draw."""
    from auto_factory.viz import RESOURCE_COLOR, BUILDING_COLOR, ARROW

    # background fill
    draw.rectangle(
        [base_x, base_y, base_x + panel_w, base_y + gmap.height * cell_px],
        fill=(252, 252, 252),
    )
    # resource shading
    for (x, y), r in gmap.resources.items():
        col = RESOURCE_COLOR[r]
        px = base_x + x * cell_px
        py = base_y + y * cell_px
        draw.rectangle([px, py, px + cell_px - 1, py + cell_px - 1], fill=col)
    # grid
    for x in range(gmap.width + 1):
        gx = base_x + x * cell_px
        draw.line(
            [(gx, base_y), (gx, base_y + gmap.height * cell_px)],
            fill=(220, 220, 220), width=1,
        )
    for y in range(gmap.height + 1):
        gy = base_y + y * cell_px
        draw.line(
            [(base_x, gy), (base_x + gmap.width * cell_px, gy)],
            fill=(220, 220, 220), width=1,
        )
    # buildings
    bld = _bld_map(plan)
    for pos, b in bld.items():
        x, y = pos
        px = base_x + x * cell_px
        py = base_y + y * cell_px
        color = BUILDING_COLOR[b.type]
        if b.type == BuildingType.BELT:
            inset = max(2, cell_px // 8)
            draw.rectangle(
                [px + inset, py + inset, px + cell_px - inset, py + cell_px - inset],
                fill=color, outline=(80, 60, 0),
            )
        else:
            draw.rectangle(
                [px + 1, py + 1, px + cell_px - 2, py + cell_px - 2],
                fill=color, outline=(0, 0, 0),
            )


def main() -> int:
    args = parse_args()
    from PIL import Image, ImageDraw, ImageFont

    # load each method's update sequence
    method_updates = []
    for (name, log, color) in METHODS:
        path = HERE / log
        if not path.exists():
            print(f"  skipping {name}: {log} not found")
            continue
        ups = _load_best_updates(path)
        sampled = _sample_at_fractions(ups, args.n_frames)
        method_updates.append((name, color, ups, sampled))
        print(f"  {name}: {len(ups)} best-updates → sampled to {len(sampled)} frames")

    if not method_updates:
        print("no logs")
        return 1

    gmap = generate_map(seed=args.seed)
    panel_w = gmap.width * args.cell_px
    panel_h = gmap.height * args.cell_px

    canvas_W = 60 + len(method_updates) * (panel_w + 40)
    score_panel_h = 140
    canvas_H = 60 + score_panel_h + 36 + panel_h + 40

    # determine score axis
    all_scores: list[float] = []
    for (name, color, ups, sampled) in method_updates:
        all_scores.extend([u["score"] for u in ups])
    lo, hi = min(all_scores), max(all_scores)
    span = max(1e-6, hi - lo)

    # try to load fonts
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=22)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=14)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=11)
    except OSError:
        title_font = ImageFont.load_default()
        font = title_font
        small = title_font

    pil_frames = []
    for frame_idx in range(args.n_frames):
        img = Image.new("RGB", (canvas_W, canvas_H), (250, 250, 252))
        draw = ImageDraw.Draw(img)

        # title
        draw.text(
            (30, 14),
            f"Auto Factory — trio convergence (frame {frame_idx + 1}/{args.n_frames})",
            fill=(20, 20, 20), font=title_font,
        )

        # score panel: shared running-best curves up to current fraction
        sp_x0, sp_y0 = 60, 56
        sp_x1, sp_y1 = canvas_W - 60, 56 + score_panel_h
        draw.rectangle([sp_x0, sp_y0, sp_x1, sp_y1], outline=(180, 180, 180))

        def sp_xy(frac: float, score: float) -> tuple[int, int]:
            x = sp_x0 + int(frac * (sp_x1 - sp_x0))
            y = sp_y1 - int((score - lo) / span * (sp_y1 - sp_y0))
            return x, y

        # axis labels
        for fr in (0.0, 0.25, 0.5, 0.75, 1.0):
            gy = sp_y1 - int(fr * (sp_y1 - sp_y0))
            draw.line([(sp_x0, gy), (sp_x1, gy)], fill=(235, 235, 240), width=1)
            val = lo + fr * span
            draw.text((sp_x0 - 38, gy - 6), f"{val:.1f}", fill=(120, 120, 120), font=small)

        cur_frac = frame_idx / max(1, args.n_frames - 1)
        # mark current position
        draw.line(
            [(sp_xy(cur_frac, lo)[0], sp_y0), (sp_xy(cur_frac, lo)[0], sp_y1)],
            fill=(200, 200, 210), width=1,
        )

        # draw each method's curve up to cur_frac
        legend_y = sp_y0 + 4
        for (name, color, ups, sampled) in method_updates:
            # plot the full curve, but draw a fade for past portion and bold for current
            pts = [
                sp_xy(j / max(1, len(ups) - 1), u["score"])
                for j, u in enumerate(ups)
            ]
            cut_idx = int(round(cur_frac * (len(ups) - 1)))
            if cut_idx >= 1:
                draw.line(pts[: cut_idx + 1], fill=color, width=3)
            if cut_idx + 1 < len(pts):
                fade = tuple(int(c * 0.4 + 255 * 0.6) for c in color)
                draw.line(pts[cut_idx:], fill=fade, width=1)
            # current marker
            x, y = pts[cut_idx]
            draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=color)
            # legend
            draw.text((sp_x1 + 8, legend_y), name, fill=color, font=small)
            draw.text(
                (sp_x1 + 8, legend_y + 12),
                f"  best so far: {ups[cut_idx]['score']:.2f}",
                fill=(80, 80, 80), font=small,
            )
            legend_y += 30

        # method-panel headers
        panel_y = sp_y1 + 36
        for i, (name, color, ups, sampled) in enumerate(method_updates):
            base_x = 60 + i * (panel_w + 40)
            draw.text(
                (base_x, panel_y - 24),
                f"{name}   score {sampled[frame_idx]['score']:.2f}",
                fill=color, font=font,
            )

            # render factory layout for this method's sampled[frame_idx]
            factory_plan.CONFIG = sampled[frame_idx]["cfg"]
            plan = factory_plan.plan(gmap)
            _render_factory_panel(
                draw, base_x, panel_y, gmap, plan, args.cell_px, panel_w
            )

        # convert frame
        pil_frames.append(img.convert("P", palette=Image.ADAPTIVE))

    durations = [args.frame_ms] * (len(pil_frames) - 1) + [args.frame_ms * 3]
    out_path = HERE / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pil_frames[0].save(
        out_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=2,
    )
    print(f"  out -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
