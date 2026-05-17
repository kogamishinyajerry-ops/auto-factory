"""Belt-routing helper for planners.

`lay_belts(plan, occupied, gmap, src, dst)` lays an L-shaped belt chain
between two machine positions, satisfying the simulation's push rules:

  - First belt's flow direction must point AWAY from `src` (so the
    upstream machine can push into it).
  - Last belt's flow direction must point AT `dst` (so it feeds the
    downstream machine).

Tries horizontal-first then vertical-first; first orientation that
collision-checks and direction-checks clean wins. Returns False without
placing anything if neither orientation works.
"""

from __future__ import annotations

from typing import List, Set, Tuple

from .types import Building, BuildingType, Direction, GameMap, Plan

VEC2DIR = {
    (1, 0): Direction.E,
    (-1, 0): Direction.W,
    (0, 1): Direction.S,
    (0, -1): Direction.N,
}


def _walk_path(
    src: Tuple[int, int],
    dst: Tuple[int, int],
    horizontal_first: bool,
) -> List[Tuple[int, int]]:
    sx, sy = src
    dx, dy = dst
    cells: List[Tuple[int, int]] = []
    cx, cy = sx, sy

    if horizontal_first:
        step = 1 if dx > sx else (-1 if dx < sx else 0)
        while cx != dx:
            cx += step
            cells.append((cx, cy))
        step = 1 if dy > cy else (-1 if dy < cy else 0)
        while cy != dy:
            cy += step
            cells.append((cx, cy))
    else:
        step = 1 if dy > sy else (-1 if dy < sy else 0)
        while cy != dy:
            cy += step
            cells.append((cx, cy))
        step = 1 if dx > cx else (-1 if dx < cx else 0)
        while cx != dx:
            cx += step
            cells.append((cx, cy))
    if cells and cells[-1] == dst:
        cells = cells[:-1]
    return cells


def _try_orientation(
    src: Tuple[int, int],
    dst: Tuple[int, int],
    horizontal_first: bool,
    occupied: Set[Tuple[int, int]],
    gmap: GameMap,
) -> List[Tuple[Tuple[int, int], Direction]] | None:
    cells = _walk_path(src, dst, horizontal_first)
    if not cells:
        return None
    placements: List[Tuple[Tuple[int, int], Direction]] = []
    for i, c in enumerate(cells):
        nxt = cells[i + 1] if i + 1 < len(cells) else dst
        vec = (nxt[0] - c[0], nxt[1] - c[1])
        d = VEC2DIR.get(vec)
        if d is None:
            return None
        placements.append((c, d))

    first_vec = (cells[0][0] - src[0], cells[0][1] - src[1])
    if placements[0][1] != VEC2DIR.get(first_vec):
        return None  # would turn immediately after src — producer can't push

    for c, _ in placements:
        if c in occupied or not gmap.in_bounds(*c):
            return None
    return placements


def lay_belts(
    plan: Plan,
    occupied: Set[Tuple[int, int]],
    gmap: GameMap,
    src: Tuple[int, int],
    dst: Tuple[int, int],
) -> bool:
    """Lay an L-shaped belt chain from src to dst. Returns True on success."""
    if src == dst:
        return False

    # Prefer the orientation whose first leg is along the longer axis (fewer
    # corners), but fall back to the other if it doesn't route cleanly.
    prefer_horizontal = abs(dst[0] - src[0]) >= abs(dst[1] - src[1])
    for horizontal_first in (prefer_horizontal, not prefer_horizontal):
        placements = _try_orientation(src, dst, horizontal_first, occupied, gmap)
        if placements is None:
            continue
        for c, d in placements:
            plan.add(Building(BuildingType.BELT, c[0], c[1], d))
            occupied.add(c)
        return True
    return False
