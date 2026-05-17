from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .types import (
    Building,
    BuildingType,
    Direction,
    GameMap,
    Plan,
    Resource,
)

# --- Tunable simulation constants ---
TICKS_PER_SECOND = 1
SIM_TICKS = 600  # ~10 minutes of game-time

MINER_PERIOD = 2  # one ore every 2 ticks
SMELTER_PERIOD = 2  # one plate every 2 ticks
ASSEMBLER_PERIOD = 2  # one widget every 2 ticks (consumes 2 plates → matches 2 smelters)
BELT_CAPACITY = 4

# Recipes
ORE_TO_PLATE = {
    "iron": "iron_plate",
    "copper": "copper_plate",
    "coal": "coal_block",
    "oil": "oil_drum",
}
PLATE_TYPES = set(ORE_TO_PLATE.values())


@dataclass
class SimResult:
    valid: bool
    reason: str = ""
    widgets: int = 0
    ticks: int = 0
    widgets_per_minute: float = 0.0
    congestion: int = 0
    crossings: int = 0  # belt cells with conflicting parallel flows
    energy_total: float = 0.0
    building_cost: float = 0.0
    raw_per_minute: Dict[str, float] = field(default_factory=dict)
    distinct_plates_used: int = 0   # 0..4; how many plate types reached an assembler


def _validate(plan: Plan, gmap: GameMap) -> Tuple[bool, str, Dict[Tuple[int, int], Building]]:
    bld: Dict[Tuple[int, int], Building] = {}
    for b in plan.buildings:
        if not gmap.in_bounds(b.x, b.y):
            return False, f"out_of_bounds at ({b.x},{b.y})", {}
        if b.pos in bld:
            return False, f"overlap at ({b.x},{b.y})", {}
        if b.type == BuildingType.MINER and gmap.resource_at(b.x, b.y) is None:
            return False, f"miner not on resource at ({b.x},{b.y})", {}
        bld[b.pos] = b
    return True, "", bld


def _count_crossings(bld: Dict[Tuple[int, int], Building]) -> int:
    """Heuristic: count belt cells that are 'crossed' by perpendicular neighbor flows.

    We say a belt at p with direction d is "crossed" when a neighbor belt
    perpendicular to d points across p (i.e. its flow line passes through p
    if conceptually extended). Cheap proxy for messy layouts.
    """
    crossings = 0
    for pos, b in bld.items():
        if b.type != BuildingType.BELT or b.direction is None:
            continue
        d = b.direction.delta
        # neighbors perpendicular to flow
        perp = [(-d[1], d[0]), (d[1], -d[0])]
        for px, py in perp:
            np = (pos[0] + px, pos[1] + py)
            nb = bld.get(np)
            if nb is None or nb.type != BuildingType.BELT or nb.direction is None:
                continue
            nd = nb.direction.delta
            # neighbor pointing back at me from perpendicular = crossing
            if (nd[0], nd[1]) == (-px, -py):
                crossings += 1
    return crossings // 2  # double counted


def simulate(plan: Plan, gmap: GameMap, ticks: int = SIM_TICKS) -> SimResult:
    ok, reason, bld = _validate(plan, gmap)
    if not ok:
        return SimResult(valid=False, reason=reason, ticks=ticks)

    # state
    belts: Dict[Tuple[int, int], List[str]] = {}
    machines: Dict[Tuple[int, int], dict] = {}
    output_count = 0
    raw_counts: Dict[str, int] = {}
    congestion = 0
    plate_types_seen: set[str] = set()  # which plate types ever entered an assembler

    for pos, b in bld.items():
        if b.type == BuildingType.BELT:
            belts[pos] = []
        elif b.type in (BuildingType.SMELTER, BuildingType.ASSEMBLER):
            machines[pos] = {"input": [], "progress": 0, "output": None}
        elif b.type == BuildingType.MINER:
            machines[pos] = {"progress": 0, "output": None}

    sorted_positions = sorted(bld.keys())

    # Pre-compute the terminus of each belt chain so producers can refuse to
    # push the wrong item type into a chain that ends at an incompatible
    # consumer. Terminus = first non-belt cell encountered following each
    # belt's direction (or the cell where a loop closes).
    def _trace_terminus(start: Tuple[int, int]) -> Tuple[int, int]:
        pos = start
        visited: set[Tuple[int, int]] = set()
        while True:
            b = bld.get(pos)
            if b is None or b.type != BuildingType.BELT or pos in visited:
                return pos
            visited.add(pos)
            bd = b.direction.delta if b.direction else (0, 0)
            pos = (pos[0] + bd[0], pos[1] + bd[1])

    belt_terminus: Dict[Tuple[int, int], Tuple[int, int]] = {
        p: _trace_terminus(p) for p in belts
    }

    def push_to_neighbor_belt(pos: Tuple[int, int], item: str) -> bool:
        # try N E S W in fixed order
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            np = (pos[0] + dx, pos[1] + dy)
            if np not in belts or len(belts[np]) >= BELT_CAPACITY:
                continue
            belt_b = bld[np]
            bd = belt_b.direction.delta if belt_b.direction else (0, 0)
            # belt must be flowing AWAY from us: belt's previous cell == us
            if (np[0] - bd[0], np[1] - bd[1]) != pos:
                continue
            # don't push into a belt whose CHAIN ENDS at an incompatible
            # consumer — that deadlocks the line. Two distinct producers can
            # otherwise compete for the same long belt and route the wrong
            # item type all the way through to the wrong smelter/assembler.
            terminus = belt_terminus.get(np, np)
            ds_b = bld.get(terminus)
            if ds_b is not None:
                if ds_b.type == BuildingType.SMELTER and item not in ORE_TO_PLATE:
                    continue
                if ds_b.type == BuildingType.ASSEMBLER and item not in PLATE_TYPES:
                    continue
            belts[np].append(item)
            return True
        return False

    for _t in range(ticks):
        # --- Phase A: miners produce ---
        for pos in sorted_positions:
            b = bld[pos]
            if b.type != BuildingType.MINER:
                continue
            m = machines[pos]
            if m["output"] is None:
                m["progress"] += 1
                if m["progress"] >= MINER_PERIOD:
                    m["progress"] = 0
                    res = gmap.resource_at(*pos)
                    if res is not None:
                        m["output"] = res.value
                        raw_counts[res.value] = raw_counts.get(res.value, 0) + 1
            # try push
            if m["output"] is not None and push_to_neighbor_belt(pos, m["output"]):
                m["output"] = None

        # --- Phase B: machine processing + push ---
        for pos in sorted_positions:
            b = bld[pos]
            if b.type == BuildingType.SMELTER:
                m = machines[pos]
                if m["output"] is None and m["input"]:
                    m["progress"] += 1
                    if m["progress"] >= SMELTER_PERIOD:
                        m["progress"] = 0
                        ore = m["input"].pop(0)
                        m["output"] = ORE_TO_PLATE.get(ore, ore)
                if m["output"] is not None and push_to_neighbor_belt(pos, m["output"]):
                    m["output"] = None

            elif b.type == BuildingType.ASSEMBLER:
                m = machines[pos]
                inputs = m["input"]
                # widget recipe: any 2 *different* plate types
                plates_present = [p for p in inputs if p in PLATE_TYPES]
                distinct = list(dict.fromkeys(plates_present))
                if m["output"] is None and len(distinct) >= 2:
                    m["progress"] += 1
                    if m["progress"] >= ASSEMBLER_PERIOD:
                        m["progress"] = 0
                        a, c = distinct[0], distinct[1]
                        inputs.remove(a)
                        inputs.remove(c)
                        m["output"] = "widget"
                if m["output"] is not None and push_to_neighbor_belt(pos, m["output"]):
                    m["output"] = None

        # --- Phase C: belt shift (snapshot semantics) ---
        next_belts: Dict[Tuple[int, int], List[str]] = {p: list(q) for p, q in belts.items()}

        # Process belts in flow order: shift head toward downstream if space
        for pos in sorted_positions:
            b = bld[pos]
            if b.type != BuildingType.BELT:
                continue
            queue = next_belts[pos]
            if not queue:
                continue
            d = b.direction.delta
            np = (pos[0] + d[0], pos[1] + d[1])
            target = bld.get(np)
            if target is None:
                continue
            item = queue[0]

            if target.type == BuildingType.BELT:
                # ensure target belt's flow direction allows entry (any direction except pointing back into me)
                td = target.direction.delta if target.direction else (0, 0)
                if (np[0] + td[0], np[1] + td[1]) == pos:
                    # would form a 2-cell loop, treat as blocked
                    continue
                if len(next_belts[np]) < BELT_CAPACITY:
                    next_belts[np].append(item)
                    queue.pop(0)
            elif target.type in (BuildingType.SMELTER, BuildingType.ASSEMBLER):
                mt = machines[np]
                # smelter: holds up to 4 items; only accepts ore (not plate/widget)
                if target.type == BuildingType.SMELTER:
                    if item in ORE_TO_PLATE and len(mt["input"]) < 4:
                        mt["input"].append(item)
                        queue.pop(0)
                else:  # assembler
                    if item in PLATE_TYPES and len(mt["input"]) < 6:
                        mt["input"].append(item)
                        plate_types_seen.add(item)
                        queue.pop(0)
            elif target.type == BuildingType.OUTPUT:
                if item == "widget":
                    output_count += 1
                # any item reaching output is consumed (waste = also consumed)
                queue.pop(0)

        belts = next_belts

        # congestion count
        for q in belts.values():
            if len(q) >= BELT_CAPACITY:
                congestion += 1

    crossings = _count_crossings(bld)

    # energy = sum of per-building per-tick energy
    from .types import BUILDING_ENERGY, BUILDING_COST

    energy = sum(BUILDING_ENERGY[b.type] for b in plan.buildings) * ticks
    bcost = sum(BUILDING_COST[b.type] for b in plan.buildings)

    seconds = ticks / TICKS_PER_SECOND
    minutes = seconds / 60.0
    raw_per_minute = {k: v / minutes for k, v in raw_counts.items()} if minutes > 0 else {}

    return SimResult(
        valid=True,
        reason="",
        widgets=output_count,
        ticks=ticks,
        widgets_per_minute=output_count / minutes if minutes > 0 else 0.0,
        congestion=congestion,
        crossings=crossings,
        energy_total=energy,
        building_cost=bcost,
        raw_per_minute=raw_per_minute,
        distinct_plates_used=len(plate_types_seen),
    )
