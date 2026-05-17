"""v1_multi_lane — up to 3 parallel chains in horizontal y-bands.

Strategy:
  - Lane center candidates at y = h/6, h/2, 5h/6 (3 horizontal slots).
  - For each lane, pick the unused iron + copper miner cells whose y is
    closest to the lane center.
  - Build the lane atomically: place 2 miners + 2 smelters + 1 assembler +
    1 output, then route 5 belt chains. If any step fails, ROLL BACK the
    entire lane (so we don't leave orphan belts/machines from the failed
    attempt).
  - Skip lane if no unused iron/copper cell is available.

This typically delivers 1-3 working chains per map, scaling widgets/min
linearly. The cap is ~30 widgets/min per chain (assembler bottleneck).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from auto_factory import Building, BuildingType, GameMap, Plan, Resource, lay_belts


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

    lane_ys = [gmap.height // 6, gmap.height // 2, 5 * gmap.height // 6]
    used: Set[Tuple[int, int]] = set()

    for lane_y in lane_ys:
        iron_pos = _pick_closest(iron_cells, lane_y, used)
        if iron_pos is None:
            continue
        copper_pos = _pick_closest(copper_cells, lane_y, used | {iron_pos})
        if copper_pos is None:
            continue
        if _try_build_lane(p, occupied, gmap, iron_pos, copper_pos, lane_y):
            used.add(iron_pos)
            used.add(copper_pos)

    return p


# ---- internals ----

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
) -> bool:
    if lane_y < 1 or lane_y >= gmap.height - 1:
        return False

    asm_x = gmap.width - 3
    out_x = gmap.width - 1
    sm_iron = (asm_x - 3, lane_y - 1)
    sm_cu = (asm_x - 3, lane_y + 1)
    asm = (asm_x, lane_y)
    out = (out_x, lane_y)

    if sm_iron[0] < 2:
        return False

    # Snapshot for atomic rollback.
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
