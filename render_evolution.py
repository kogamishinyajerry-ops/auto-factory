#!/usr/bin/env python3
"""Render an animated GIF showing how the best plan evolved across the loop.

Walks an iterate*.jsonl log, picks every row that strictly improved
running-best, and renders that CONFIG's factory layout on a fixed seed
map. Frames are stitched into an animated GIF — gives a real visual sense
of what "the autonomous loop discovered" looks like over time.

Usage:
    python render_evolution.py --log results/iterate_hybrid.jsonl
    python render_evolution.py --log results/iterate.jsonl --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import factory_plan  # noqa: E402
from auto_factory import generate_map, render_png, simulate, score_plan  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True,
                    help="JSONL log from iterate*.py")
    ap.add_argument("--out", default="results/evolution.gif")
    ap.add_argument("--seed", type=int, default=7,
                    help="map seed used for every frame")
    ap.add_argument("--frame-ms", type=int, default=900)
    ap.add_argument("--cell-px", type=int, default=28)
    ap.add_argument("--keep-frames", action="store_true",
                    help="don't delete the per-frame PNG dir after stitching")
    return ap.parse_args()


def _load_best_updates(log: Path) -> list[dict]:
    """Walk log, return only rows where running-best strictly increased."""
    out = []
    cur_best = float("-inf")
    for line in log.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        # skip sentinels and meta rows
        if r.get("iter", 0) < 0:
            continue
        if "score" not in r or "cfg" not in r:
            continue
        if r.get("source") == "basin_proposal":
            continue
        s = float(r["score"])
        if s > cur_best:
            cur_best = s
            out.append({
                "iter": r.get("iter", len(out)),
                "score": s,
                "cfg": r["cfg"],
                "basin": r.get("basin"),
                "source": r.get("source", ""),
            })
    return out


def _render_frame(
    cfg: dict, seed: int, label: str, path: Path, cell_px: int
) -> None:
    """Swap CONFIG, call factory_plan.plan() on a fixed map, render PNG."""
    factory_plan.CONFIG = cfg
    gmap = generate_map(seed=seed)
    plan = factory_plan.plan(gmap)
    # also measure throughput on this single map for the title
    sim = simulate(plan, gmap, ticks=600)
    sb = score_plan(sim)
    title = f"{label}   |   single-map score {sb.total:+.1f}  ({sim.widgets} widgets / {sim.ticks}t)"
    render_png(plan, gmap, path, title=title, cell_px=cell_px)


def main() -> int:
    args = parse_args()
    log_path = Path(args.log)
    if not log_path.is_absolute():
        log_path = HERE / log_path
    if not log_path.exists():
        print(f"log not found: {log_path}", file=sys.stderr)
        return 1

    updates = _load_best_updates(log_path)
    if not updates:
        print("no best-updates in log — nothing to render")
        return 1

    print(f"  {log_path.name}: {len(updates)} best-updates → frames")

    frames_dir = HERE / (args.out.removesuffix(".gif") + "_frames")
    frames_dir.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    pil_frames: list[Image.Image] = []
    for i, u in enumerate(updates):
        basin = u.get("basin")
        basin_tag = f"basin {basin}" if basin else ""
        label = (
            f"step {i + 1}/{len(updates)}   bench-eval {u['score']:.2f}"
            + (f"   ({basin_tag} · {u['source']})" if basin_tag or u['source'] else "")
        )
        frame_path = frames_dir / f"frame_{i:03d}.png"
        _render_frame(u["cfg"], args.seed, label, frame_path, args.cell_px)
        pil_frames.append(Image.open(frame_path).convert("P", palette=Image.ADAPTIVE))
        print(f"    [{i + 1:>2}/{len(updates)}] score={u['score']:.2f}")

    # hold final frame a bit longer
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

    if not args.keep_frames:
        for f in frames_dir.glob("frame_*.png"):
            f.unlink()
        frames_dir.rmdir()

    return 0


if __name__ == "__main__":
    sys.exit(main())
