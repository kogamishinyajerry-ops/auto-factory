"""v3_greedy_search — generate K candidate plans, simulate, keep the best.

This is the first "AutoResearch-shaped" planner: it doesn't pretend to
have one fixed strategy. Instead it sweeps a small portfolio:

  - 3 different LANE_CONFIGS (staggered / all-17 / 3-lane-v1-style)
  - 3 different miner-pick heuristics (closest-y / leftmost / min-route-distance)
  - 1 feasibility filter (skip a lane if its closest iron or copper miner
    would need more than `max_route_dist` Manhattan steps to its smelter)

That's up to 7 candidate plans per map. Each one is built atomically
(rollback on collision) the same way v1/v2 do. We then simulate each
plan for `EVAL_TICKS` ticks, score, and return the highest-scoring one.

Cost: ~7× simulation per call. Sim is ~5ms so total ~35ms/map — still
fast enough to bench 50 maps in <2s.

Designed to fix v2 regressions like seed 18, where v2's fixed config
forces miners too far from their smelter. v3 tries dropping that lane
or shifting its config and keeps whichever scores higher.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set, Tuple

from auto_factory import (
    Building,
    BuildingType,
    GameMap,
    Plan,
    Resource,
    lay_belts,
    score_plan,
    simulate,
)

EVAL_TICKS = 600  # match eval.py default; if you change there, mirror here


# Lane configuration sets we'll sweep over.
_CONFIGS_DEFAULT = [(1, 17), (4, 15), (7, 17), (10, 15), (13, 17)]   # v2's stagger
_CONFIGS_REV = [(1, 15), (4, 17), (7, 15), (10, 17), (13, 15)]       # opposite stagger
_CONFIGS_ALL17 = [(1, 17), (4, 17), (7, 17), (10, 17), (13, 17)]     # no stagger
_CONFIGS_V1 = [(2, 17), (7, 17), (12, 17)]                            # v1's 3-lane
_CONFIGS_SHIFT = [(2, 17), (5, 15), (8, 17), (11, 15), (14, 17)]      # default shifted down 1
_CONFIGS_NARROW4 = [(2, 17), (5, 15), (8, 17), (11, 15)]              # 4 lanes (top heavy)

LANE_CONFIG_SETS = {
    "default": _CONFIGS_DEFAULT,
    "rev": _CONFIGS_REV,
    "all17": _CONFIGS_ALL17,
    "v1_3lanes": _CONFIGS_V1,
    "shift_down": _CONFIGS_SHIFT,
    "narrow_4": _CONFIGS_NARROW4,
}

# Miner-pick heuristics:
#   closest_y   — pick miner whose y is closest to lane_y
#   leftmost    — pick miner with smallest x first
#   min_route   — pick miner minimising Manhattan distance to its smelter
MINER_PICKS = ("closest_y", "leftmost", "min_route")

# Strategy portfolio (config_name, miner_pick, max_route_dist or None)
STRATEGIES = [
    ("default", "closest_y", None),
    ("default", "leftmost", None),
    ("default", "min_route", None),
    ("default", "min_route", 16),
    ("rev", "min_route", None),
    ("all17", "closest_y", None),
    ("v1_3lanes", "closest_y", None),
]


def plan(gmap: GameMap) -> Plan:
    best_plan = Plan()
    best_score = float("-inf")

    for config_name, miner_pick, max_route in STRATEGIES:
        candidate = _build_candidate(
            gmap,
            LANE_CONFIG_SETS[config_name],
            miner_pick,
            max_route,
        )
        sim = simulate(candidate, gmap, ticks=EVAL_TICKS)
        sb = score_plan(sim)
        if sb.total > best_score:
            best_score = sb.total
            best_plan = candidate

    return best_plan


# ---- candidate construction ---------------------------------------------


def _build_candidate(
    gmap: GameMap,
    lane_configs: List[Tuple[int, int]],
    miner_pick: str,
    max_route: Optional[int],
) -> Plan:
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
    for lane_y, asm_x in lane_configs:
        sm_x = asm_x - 3
        if sm_x < 2 or lane_y < 1 or lane_y >= gmap.height - 1:
            continue

        sm_iron_target = (sm_x, lane_y - 1)
        sm_cu_target = (sm_x, lane_y + 1)

        iron_pos = _pick_miner(
            iron_cells, lane_y, sm_iron_target, used, miner_pick
        )
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

        if _try_build_lane(p, occupied, gmap, iron_pos, copper_pos, lane_y, asm_x):
            used.add(iron_pos)
            used.add(copper_pos)
    return p


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
) -> bool:
    out_x = gmap.width - 1
    sm_iron = (asm_x - 3, lane_y - 1)
    sm_cu = (asm_x - 3, lane_y + 1)
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
