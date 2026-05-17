"""Parameterised lane builder.

A *spec* fully describes how the planner should lay out lanes:

    {
      "lane_ys":         [int, ...],            # vertical placement of each lane
      "asm_xs":          [int, ...],            # asm column per lane (same length)
      "lane_resources":  [(Resource, Resource), ...],
                                                # ore types this lane mines.
                                                # defaults to (iron, copper) per
                                                # lane if absent.
      "smelter_offset":  int,                    # smelter_x = asm_x - offset
      "miner_pick":      "closest_y" | "leftmost" | "min_route",
      "max_route_dist":  int or None,            # skip lane if min route > this
    }

`build_from_spec(gmap, spec)` returns a Plan. Each lane is built atomically
(machines + 5 belt chains) with rollback on partial failure, the same way
plans/v3_greedy_search does — just with the lane-shape constants now
caller-supplied instead of hard-coded.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set, Tuple

from .routing import lay_belts
from .types import (
    Building,
    BuildingType,
    GameMap,
    Plan,
    Resource,
)


def build_from_spec(gmap: GameMap, spec: dict) -> Plan:
    p = Plan()
    occupied: Set[Tuple[int, int]] = set()

    lane_ys: List[int] = spec["lane_ys"]
    asm_xs: List[int] = spec["asm_xs"]
    if len(lane_ys) != len(asm_xs):
        raise ValueError(
            f"lane_ys ({len(lane_ys)}) and asm_xs ({len(asm_xs)}) must match"
        )
    lane_resources: List[Tuple[Resource, Resource]] = spec.get(
        "lane_resources",
        [(Resource.IRON, Resource.COPPER)] * len(lane_ys),
    )
    if len(lane_resources) != len(lane_ys):
        raise ValueError(
            f"lane_resources ({len(lane_resources)}) must match lane count ({len(lane_ys)})"
        )
    smelter_offset: int = spec.get("smelter_offset", 3)
    miner_pick: str = spec.get("miner_pick", "closest_y")
    max_route: Optional[int] = spec.get("max_route_dist")

    by_type: Dict[Resource, List[Tuple[int, int]]] = {}
    for pos, r in gmap.resources.items():
        by_type.setdefault(r, []).append(pos)

    used: Set[Tuple[int, int]] = set()
    for lane_y, asm_x, (r_north, r_south) in zip(lane_ys, asm_xs, lane_resources):
        sm_x = asm_x - smelter_offset
        if sm_x < 2 or lane_y < 1 or lane_y >= gmap.height - 1:
            continue
        if asm_x >= gmap.width - 1:
            continue
        # need at least one cell of each requested resource on the map
        if r_north not in by_type or r_south not in by_type:
            continue
        if r_north == r_south:
            continue  # assembler needs two DISTINCT plate types

        cells_north = sorted(by_type[r_north], key=lambda c: (c[1], c[0]))
        cells_south = sorted(by_type[r_south], key=lambda c: (c[1], c[0]))

        sm_north_target = (sm_x, lane_y - 1)
        sm_south_target = (sm_x, lane_y + 1)

        miner_n = _pick_miner(cells_north, lane_y, sm_north_target, used, miner_pick)
        if miner_n is None:
            continue
        if max_route is not None and _manhattan(miner_n, sm_north_target) > max_route:
            continue
        miner_s = _pick_miner(
            cells_south, lane_y, sm_south_target, used | {miner_n}, miner_pick
        )
        if miner_s is None:
            continue
        if max_route is not None and _manhattan(miner_s, sm_south_target) > max_route:
            continue

        if _try_build_lane(
            p,
            occupied,
            gmap,
            miner_n,
            miner_s,
            lane_y,
            asm_x,
            sm_x,
        ):
            used.add(miner_n)
            used.add(miner_s)
    return p


# ---- internals ----------------------------------------------------------


def _manhattan(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _pick_miner(
    cells: List[Tuple[int, int]],
    lane_y: int,
    smelter_target: Tuple[int, int],
    forbidden: Set[Tuple[int, int]],
    strategy: str,
) -> Optional[Tuple[int, int]]:
    candidates = [c for c in cells if c not in forbidden]
    if not candidates:
        return None
    if strategy == "closest_y":
        key: Callable[[Tuple[int, int]], tuple] = lambda c: (abs(c[1] - lane_y), c[0])
    elif strategy == "leftmost":
        key = lambda c: (c[0], c[1])
    elif strategy == "min_route":
        key = lambda c: (_manhattan(c, smelter_target), c[0])
    else:
        raise ValueError(strategy)
    return min(candidates, key=key)


def _try_build_lane(
    p: Plan,
    occupied: Set[Tuple[int, int]],
    gmap: GameMap,
    miner_north: Tuple[int, int],
    miner_south: Tuple[int, int],
    lane_y: int,
    asm_x: int,
    sm_x: int,
) -> bool:
    out_x = gmap.width - 1
    sm_north = (sm_x, lane_y - 1)
    sm_south = (sm_x, lane_y + 1)
    asm = (asm_x, lane_y)
    out = (out_x, lane_y)

    snapshot_buildings = list(p.buildings)
    snapshot_occupied = set(occupied)

    def rollback() -> bool:
        p.buildings[:] = snapshot_buildings
        occupied.clear()
        occupied.update(snapshot_occupied)
        return False

    machines = [
        Building(BuildingType.MINER, *miner_north),
        Building(BuildingType.MINER, *miner_south),
        Building(BuildingType.SMELTER, *sm_north),
        Building(BuildingType.SMELTER, *sm_south),
        Building(BuildingType.ASSEMBLER, *asm),
        Building(BuildingType.OUTPUT, *out),
    ]
    for b in machines:
        if b.pos in occupied or not gmap.in_bounds(b.x, b.y):
            return rollback()
        p.add(b)
        occupied.add(b.pos)

    routes = [
        (miner_north, sm_north),
        (miner_south, sm_south),
        (sm_north, asm),
        (sm_south, asm),
        (asm, out),
    ]
    for src, dst in routes:
        if not lay_belts(p, occupied, gmap, src, dst):
            return rollback()
    return True
