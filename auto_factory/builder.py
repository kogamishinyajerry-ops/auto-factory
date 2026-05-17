"""Parameterised lane builder.

A *spec* fully describes how the planner should lay out lanes:

    {
      "lane_ys":         [int, ...],          # vertical placement of each lane
      "asm_xs":          [int, ...],          # asm column per lane (same length)
      "smelter_offset":  int,                  # smelter_x = asm_x - offset
      "miner_pick":      "closest_y" | "leftmost" | "min_route",
      "max_route_dist":  int or None,          # skip lane if min route > this
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
    smelter_offset: int = spec.get("smelter_offset", 3)
    miner_pick: str = spec.get("miner_pick", "closest_y")
    max_route: Optional[int] = spec.get("max_route_dist")

    by_type: Dict[Resource, List[Tuple[int, int]]] = {}
    for pos, r in gmap.resources.items():
        by_type.setdefault(r, []).append(pos)
    if Resource.IRON not in by_type or Resource.COPPER not in by_type:
        return p

    iron_cells = sorted(by_type[Resource.IRON], key=lambda c: (c[1], c[0]))
    copper_cells = sorted(by_type[Resource.COPPER], key=lambda c: (c[1], c[0]))

    used: Set[Tuple[int, int]] = set()
    for lane_y, asm_x in zip(lane_ys, asm_xs):
        sm_x = asm_x - smelter_offset
        if sm_x < 2 or lane_y < 1 or lane_y >= gmap.height - 1:
            continue
        if asm_x >= gmap.width - 1:
            continue

        sm_iron_target = (sm_x, lane_y - 1)
        sm_cu_target = (sm_x, lane_y + 1)

        iron_pos = _pick_miner(iron_cells, lane_y, sm_iron_target, used, miner_pick)
        if iron_pos is None:
            continue
        if max_route is not None and _manhattan(iron_pos, sm_iron_target) > max_route:
            continue
        copper_pos = _pick_miner(
            copper_cells, lane_y, sm_cu_target, used | {iron_pos}, miner_pick
        )
        if copper_pos is None:
            continue
        if max_route is not None and _manhattan(copper_pos, sm_cu_target) > max_route:
            continue

        if _try_build_lane(
            p,
            occupied,
            gmap,
            iron_pos,
            copper_pos,
            lane_y,
            asm_x,
            sm_x,
        ):
            used.add(iron_pos)
            used.add(copper_pos)
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
    iron_pos: Tuple[int, int],
    copper_pos: Tuple[int, int],
    lane_y: int,
    asm_x: int,
    sm_x: int,
) -> bool:
    out_x = gmap.width - 1
    sm_iron = (sm_x, lane_y - 1)
    sm_cu = (sm_x, lane_y + 1)
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
        Building(BuildingType.MINER, *iron_pos),
        Building(BuildingType.MINER, *copper_pos),
        Building(BuildingType.SMELTER, *sm_iron),
        Building(BuildingType.SMELTER, *sm_cu),
        Building(BuildingType.ASSEMBLER, *asm),
        Building(BuildingType.OUTPUT, *out),
    ]
    for b in machines:
        if b.pos in occupied or not gmap.in_bounds(b.x, b.y):
            return rollback()
        p.add(b)
        occupied.add(b.pos)

    routes = [
        (iron_pos, sm_iron),
        (copper_pos, sm_cu),
        (sm_iron, asm),
        (sm_cu, asm),
        (asm, out),
    ]
    for src, dst in routes:
        if not lay_belts(p, occupied, gmap, src, dst):
            return rollback()
    return True
