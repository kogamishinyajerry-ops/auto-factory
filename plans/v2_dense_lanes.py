"""v2_dense_lanes — 5 parallel chains with staggered smelter columns.

Why this beats v1: v1's 3 lanes all funnel copper-miner verticals through
column 14, so adjacent lanes' smelters (also at column 14) get blocked
and the middle lane almost always rolls back. v2 alternates the smelter
column 14 / 12 / 14 / 12 / 14 across 5 lane attempts (y = 1, 4, 7, 10,
13). Lanes whose vertical trunk is column 14 share with at most one
neighbor instead of all of them; lanes using column 12 avoid the column
14 fight entirely.

Each lane attempt is atomic with rollback (same primitive as v1). Lanes
that can't route cleanly leave no orphan buildings.

Layout per lane (asm_x ∈ {17, 15}):
    sm_x = asm_x - 3
    sm_iron at (sm_x, lane_y - 1)
    sm_cu   at (sm_x, lane_y + 1)
    asm     at (asm_x, lane_y)
    output  at (W - 1, lane_y)

5 lanes × 30 widgets/min cap = 150 widgets/min theoretical max.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from auto_factory import Building, BuildingType, GameMap, Plan, Resource, lay_belts


# (lane_y, asm_x) — staggered to avoid adjacent lanes fighting over the
# same smelter column. asm_x=17 uses smelter column 14; asm_x=15 uses 12.
LANE_CONFIGS = [
    (1, 17),
    (4, 15),
    (7, 17),
    (10, 15),
    (13, 17),
]


def plan(gmap: GameMap) -> Plan:
    p = Plan()
    occupied: Set[Tuple[int, int]] = set()

    by_type: Dict[Resource, List[Tuple[int, int]]] = {}
    for pos, r in gmap.resources.items():
        by_type.setdefault(r, []).append(pos)

    if Resource.IRON not in by_type or Resource.COPPER not in by_type:
        return p

    iron_cells = sorted(by_type[Resource.IRON], key=lambda c: (c[1], c[0]))
    copper_cells = sorted(by_type[Resource.COPPER], key=lambda c: (c[1], c[0]))

    used: Set[Tuple[int, int]] = set()
    for lane_y, asm_x in LANE_CONFIGS:
        iron_pos = _pick_closest(iron_cells, lane_y, used)
        if iron_pos is None:
            continue
        copper_pos = _pick_closest(copper_cells, lane_y, used | {iron_pos})
        if copper_pos is None:
            continue
        if _try_build_lane(p, occupied, gmap, iron_pos, copper_pos, lane_y, asm_x):
            used.add(iron_pos)
            used.add(copper_pos)
    return p


def _pick_closest(
    cells: List[Tuple[int, int]],
    target_y: int,
    forbidden: Set[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    candidates = [c for c in cells if c not in forbidden]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (abs(c[1] - target_y), c[0]))


def _try_build_lane(
    p: Plan,
    occupied: Set[Tuple[int, int]],
    gmap: GameMap,
    iron_pos: Tuple[int, int],
    copper_pos: Tuple[int, int],
    lane_y: int,
    asm_x: int,
) -> bool:
    if lane_y < 1 or lane_y >= gmap.height - 1:
        return False

    out_x = gmap.width - 1
    sm_iron = (asm_x - 3, lane_y - 1)
    sm_cu = (asm_x - 3, lane_y + 1)
    asm = (asm_x, lane_y)
    out = (out_x, lane_y)
    if sm_iron[0] < 2 or out_x >= gmap.width:
        return False

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
