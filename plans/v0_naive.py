"""v0_naive — archival copy of the original baseline.

Single L-shaped chain: iron miner -> smelter -> assembler <- smelter <- copper miner -> output.
Often disconnects on dense maps because both lanes share the same elbow column.
Kept around as the "do nothing fancy" lower bound for bench comparisons.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from auto_factory import Building, BuildingType, GameMap, Plan, Resource, lay_belts


def plan(gmap: GameMap) -> Plan:
    p = Plan()
    occupied: set[Tuple[int, int]] = set()

    def place(b: Building) -> bool:
        if b.pos in occupied or not gmap.in_bounds(b.x, b.y):
            return False
        p.add(b)
        occupied.add(b.pos)
        return True

    by_type: Dict[Resource, List[Tuple[int, int]]] = {}
    for pos, r in gmap.resources.items():
        by_type.setdefault(r, []).append(pos)

    if Resource.IRON not in by_type or Resource.COPPER not in by_type:
        return p

    iron_pos = sorted(by_type[Resource.IRON])[0]
    copper_pos = sorted(by_type[Resource.COPPER])[0]

    out_x = gmap.width - 1
    asm_x = gmap.width - 3
    asm_y = gmap.height // 2
    sm_iron = (asm_x - 3, asm_y - 1)
    sm_cu = (asm_x - 3, asm_y + 1)

    if sm_iron[0] < 2:
        return p

    place(Building(BuildingType.MINER, *iron_pos))
    place(Building(BuildingType.MINER, *copper_pos))
    place(Building(BuildingType.SMELTER, *sm_iron))
    place(Building(BuildingType.SMELTER, *sm_cu))
    place(Building(BuildingType.ASSEMBLER, asm_x, asm_y))
    place(Building(BuildingType.OUTPUT, out_x, asm_y))

    lay_belts(p, occupied, gmap, iron_pos, sm_iron)
    lay_belts(p, occupied, gmap, copper_pos, sm_cu)
    lay_belts(p, occupied, gmap, sm_iron, (asm_x, asm_y))
    lay_belts(p, occupied, gmap, sm_cu, (asm_x, asm_y))
    lay_belts(p, occupied, gmap, (asm_x, asm_y), (out_x, asm_y))

    return p
