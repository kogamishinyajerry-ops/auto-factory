#!/usr/bin/env python3
"""Story-arc gallery: SOTA factory layout at each milestone.

Walks the project's git history and the plans/ baselines, extracts each
phase's planner CONFIG (or imports the static planner module), renders
each on a shared seed map, and stitches them into a single PNG.

Tells the visual story of "what the autoresearch loop actually changed"
across phases A → J.

Usage:
    python render_story_arc.py
    python render_story_arc.py --seed 11 --cell-px 22
"""

from __future__ import annotations

import argparse
import ast
import importlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import factory_plan  # noqa: E402
from auto_factory import generate_map, score_plan, simulate  # noqa: E402
from auto_factory.viz import _bld_map, RESOURCE_COLOR, BUILDING_COLOR  # noqa: E402
from auto_factory.types import BuildingType  # noqa: E402


# Story milestones: (label, kind, ref/module, bench_score_50map_known).
# bench is the score at the time it was the SOTA (informational; we re-bench live).
MILESTONES = [
    ("A · v0 naive",          "planner_module", "plans.v0_naive",     7.0),
    ("A · v1 multi-lane",     "planner_module", "plans.v1_multi_lane", 18.6),
    ("B · random hill-climb", "git_ref",        "99fc551",            28.9),
    ("D · 4-worker tournament", "git_ref",      "4c4cc90",            29.6),
    ("G · phaseG tournament", "git_ref",        "3d12f4e",            43.2),
    ("J · LLM-seeded (SOTA)", "git_ref",        "80e9860",            43.8),
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/checkpoint10_story_arc.png")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--cell-px", type=int, default=22)
    return ap.parse_args()


def _extract_config_from_git_ref(ref: str) -> dict:
    """git show <ref>:factory_plan.py → ast.literal_eval the CONFIG dict."""
    proc = subprocess.run(
        ["git", "show", f"{ref}:factory_plan.py"],
        cwd=HERE, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git show failed for {ref}: {proc.stderr}")
    text = proc.stdout
    s = text.find("# === AUTORESEARCH CONFIG START ===")
    e = text.find("# === AUTORESEARCH CONFIG END ===")
    if s < 0 or e < 0:
        raise SystemExit(f"markers missing in {ref}")
    block = text[s:e]
    # find balanced { ... } after "CONFIG = "
    eq = block.find("CONFIG")
    brace = block.find("{", eq)
    depth = 0
    i = brace
    in_str = False
    str_quote = ""
    while i < len(block):
        c = block[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == str_quote:
                in_str = False
        else:
            if c in ('"', "'"):
                in_str = True
                str_quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return ast.literal_eval(block[brace : i + 1])
        i += 1
    raise SystemExit(f"unbalanced CONFIG in {ref}")


def _plan_for_milestone(kind: str, ref_or_mod: str, gmap):
    """Build the plan for this milestone on the given map."""
    if kind == "planner_module":
        mod = importlib.import_module(ref_or_mod)
        return mod.plan(gmap)
    # kind == "git_ref"
    cfg = _extract_config_from_git_ref(ref_or_mod)
    factory_plan.CONFIG = cfg
    return factory_plan.plan(gmap)


def _render_factory_panel(draw, base_x, base_y, gmap, plan, cell_px, panel_w):
    """Same as render_trio's panel drawer (extracted)."""
    draw.rectangle(
        [base_x, base_y, base_x + panel_w, base_y + gmap.height * cell_px],
        fill=(252, 252, 252),
    )
    for (x, y), r in gmap.resources.items():
        col = RESOURCE_COLOR[r]
        px = base_x + x * cell_px
        py = base_y + y * cell_px
        draw.rectangle([px, py, px + cell_px - 1, py + cell_px - 1], fill=col)
    for x in range(gmap.width + 1):
        gx = base_x + x * cell_px
        draw.line([(gx, base_y), (gx, base_y + gmap.height * cell_px)],
                  fill=(220, 220, 220), width=1)
    for y in range(gmap.height + 1):
        gy = base_y + y * cell_px
        draw.line([(base_x, gy), (base_x + gmap.width * cell_px, gy)],
                  fill=(220, 220, 220), width=1)
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

    gmap = generate_map(seed=args.seed)
    panel_w = gmap.width * args.cell_px
    panel_h = gmap.height * args.cell_px
    n = len(MILESTONES)
    cols = 3
    rows = (n + cols - 1) // cols
    pad_x, pad_y = 40, 90
    head_h = 30
    label_h = 50

    W = pad_x * 2 + cols * panel_w + (cols - 1) * 30
    H = pad_y + rows * (panel_h + head_h + label_h) + 40

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
        (pad_x, 20),
        "Auto Factory story-arc — SOTA layout per phase",
        fill=(20, 20, 20), font=title_font,
    )
    draw.text(
        (pad_x, 54),
        f"Same map seed (seed={args.seed}) for every panel — only the planner changes.  "
        f"Color: brown=iron, orange=copper, dark=coal, blue=oil; "
        f"yellow=miner, gray=smelter, purple=assembler, green=output.",
        fill=(80, 80, 80), font=small,
    )

    for idx, (label, kind, ref, known_bench) in enumerate(MILESTONES):
        row, col = divmod(idx, cols)
        base_x = pad_x + col * (panel_w + 30)
        base_y = pad_y + row * (panel_h + head_h + label_h) + head_h

        plan = _plan_for_milestone(kind, ref, gmap)
        sim = simulate(plan, gmap, ticks=600)
        sb = score_plan(sim)

        # header above panel
        draw.text((base_x, base_y - head_h + 2),
                  label, fill=(20, 20, 20), font=font)
        draw.text(
            (base_x, base_y - head_h + 20),
            f"this map: {sb.total:+.1f}  ({sim.widgets}w / 600t)   |   known 50-map bench: {known_bench:.1f}",
            fill=(80, 80, 80), font=small,
        )
        _render_factory_panel(draw, base_x, base_y, gmap, plan, args.cell_px, panel_w)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"  out -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
