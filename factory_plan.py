"""Factory layout planner — the live edit surface.

iterate.py (autonomous mutation loop) rewrites the CONFIG block below
between the AUTORESEARCH markers. Hand-editing the block is fine; the
loop will pick up whatever's there as its starting state.

CONFIG schema (Phase G — per-lane resource pairs):
    {
        "strategies": [
            {"lane_y_set":         <key into LANE_Y_SETS>,
             "asm_x_pattern":      <key into ASM_X_PATTERNS>,
             "smelter_offset":     2 | 3 | 4,
             "miner_pick":         "closest_y" | "leftmost" | "min_route",
             "max_route_dist":     int or None,
             "resource_pattern":   <key into RESOURCE_PATTERNS>},
            ...     # one or more strategies
        ]
    }

When strategies has >1 entry, plan() runs each, scores internally, and
returns the best on this map (portfolio / Mixture-of-Experts pattern).

Score = widgets_per_minute
      + 3.0   * distinct_plate_types_used   (new in Phase G)
      - 0.500 * belt_crossings
      - 0.0005* sum_energy_per_tick * ticks
      - 0.050 * total_building_cost
      - 0.001 * congestion_ticks
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from auto_factory import GameMap, Plan, Resource, build_from_spec, score_plan, simulate


# ---- declarative search dimensions iterate.py mutates over -------------

LANE_Y_SETS: Dict[str, List[int]] = {
    "y_default": [1, 4, 7, 10, 13],   # 5 evenly spaced
    "y_v1":      [2, 7, 12],          # v1's 3 lanes
    "y_shift":   [2, 5, 8, 11, 14],   # 5 shifted down
    "y_narrow":  [2, 5, 8, 11],       # top-heavy 4 lanes
    "y_dense":   [1, 3, 5, 7, 9, 11, 13],  # 7 thin lanes (often partial)
    "y_pair":    [3, 11],             # 2 lanes far apart
}

# Each pattern is a function from "number of lanes" to list of asm_x columns.
ASM_X_PATTERNS: Dict[str, Callable[[int], List[int]]] = {
    "all17":         lambda n: [17] * n,
    "all15":         lambda n: [15] * n,
    "all16":         lambda n: [16] * n,
    "stagger17_15":  lambda n: [17 if i % 2 == 0 else 15 for i in range(n)],
    "stagger15_17":  lambda n: [15 if i % 2 == 0 else 17 for i in range(n)],
    "stagger17_16":  lambda n: [17 if i % 2 == 0 else 16 for i in range(n)],
}

# 6 distinct ore-pair combinations from {iron, copper, coal, oil}.
_PAIRS_ALL = [
    (Resource.IRON, Resource.COPPER),
    (Resource.IRON, Resource.COAL),
    (Resource.IRON, Resource.OIL),
    (Resource.COPPER, Resource.COAL),
    (Resource.COPPER, Resource.OIL),
    (Resource.COAL, Resource.OIL),
]

# Each pattern is a function from "number of lanes" to a list of (ore, ore)
# pairs, one per lane. Lanes whose pair has the same ore on both sides get
# skipped by the builder (assembler needs two DISTINCT plates).
RESOURCE_PATTERNS: Dict[str, Callable[[int], List[Tuple[Resource, Resource]]]] = {
    "all_ic":     lambda n: [(Resource.IRON, Resource.COPPER)] * n,
    "all_iko":    lambda n: [(Resource.IRON, Resource.COAL)] * n,
    "all_cuoi":   lambda n: [(Resource.COPPER, Resource.OIL)] * n,
    "all_kool":   lambda n: [(Resource.COAL, Resource.OIL)] * n,
    "rotate4":    lambda n: [_PAIRS_ALL[i % 4] for i in range(n)],
    "rotate_all": lambda n: [_PAIRS_ALL[i % 6] for i in range(n)],
}

SMELTER_OFFSETS = [2, 3, 4]
MINER_PICKS = ["closest_y", "leftmost", "min_route"]
MAX_ROUTE_VALUES = [None, 10, 12, 15, 18, 25]


# === AUTORESEARCH CONFIG START ===
# (iterate.py rewrites between these markers; hand-editing is fine too)
CONFIG = {
    "strategies": [
        {
            "lane_y_set": "y_dense",
            "asm_x_pattern": "all17",
            "smelter_offset": 4,
            "miner_pick": "closest_y",
            "max_route_dist": None,
            "resource_pattern": "rotate4"
        },
        {
            "lane_y_set": "y_default",
            "asm_x_pattern": "all17",
            "smelter_offset": 2,
            "miner_pick": "leftmost",
            "max_route_dist": 25,
            "resource_pattern": "rotate_all"
        },
        {
            "lane_y_set": "y_default",
            "asm_x_pattern": "stagger17_16",
            "smelter_offset": 4,
            "miner_pick": "closest_y",
            "max_route_dist": 18,
            "resource_pattern": "all_ic"
        },
        {
            "lane_y_set": "y_v1",
            "asm_x_pattern": "all17",
            "smelter_offset": 4,
            "miner_pick": "closest_y",
            "max_route_dist": None,
            "resource_pattern": "all_ic"
        },
        {
            "lane_y_set": "y_shift",
            "asm_x_pattern": "stagger17_16",
            "smelter_offset": 2,
            "miner_pick": "leftmost",
            "max_route_dist": None,
            "resource_pattern": "rotate_all"
        },
        {
            "lane_y_set": "y_dense",
            "asm_x_pattern": "all15",
            "smelter_offset": 2,
            "miner_pick": "closest_y",
            "max_route_dist": None,
            "resource_pattern": "rotate_all"
        },
        {
            "lane_y_set": "y_v1",
            "asm_x_pattern": "stagger17_15",
            "smelter_offset": 2,
            "miner_pick": "min_route",
            "max_route_dist": 25,
            "resource_pattern": "rotate_all"
        },
        {
            "lane_y_set": "y_default",
            "asm_x_pattern": "all17",
            "smelter_offset": 3,
            "miner_pick": "closest_y",
            "max_route_dist": None,
            "resource_pattern": "rotate_all"
        },
        {
            "lane_y_set": "y_v1",
            "asm_x_pattern": "all15",
            "smelter_offset": 2,
            "miner_pick": "leftmost",
            "max_route_dist": None,
            "resource_pattern": "rotate4"
        },
        {
            "lane_y_set": "y_v1",
            "asm_x_pattern": "stagger17_15",
            "smelter_offset": 2,
            "miner_pick": "min_route",
            "max_route_dist": 18,
            "resource_pattern": "rotate4"
        },
        {
            "lane_y_set": "y_default",
            "asm_x_pattern": "all16",
            "smelter_offset": 4,
            "miner_pick": "min_route",
            "max_route_dist": 15,
            "resource_pattern": "rotate4"
        },
        {
            "lane_y_set": "y_default",
            "asm_x_pattern": "all17",
            "smelter_offset": 2,
            "miner_pick": "min_route",
            "max_route_dist": None,
            "resource_pattern": "all_ic"
        }
    ]
}
# === AUTORESEARCH CONFIG END ===

_INTERNAL_EVAL_TICKS = 600


def _expand_strategy(s: dict) -> dict:
    lane_ys = LANE_Y_SETS[s["lane_y_set"]]
    n = len(lane_ys)
    asm_xs = ASM_X_PATTERNS[s["asm_x_pattern"]](n)
    # Phase G addition; default to all-iron-copper for backward compat with
    # any old CONFIG someone hand-pastes in.
    rp_key = s.get("resource_pattern", "all_ic")
    lane_resources = RESOURCE_PATTERNS[rp_key](n)
    return {
        "lane_ys": lane_ys,
        "asm_xs": asm_xs,
        "lane_resources": lane_resources,
        "smelter_offset": s["smelter_offset"],
        "miner_pick": s["miner_pick"],
        "max_route_dist": s.get("max_route_dist"),
    }


def plan(gmap: GameMap) -> Plan:
    strategies = CONFIG["strategies"]
    if len(strategies) == 1:
        return build_from_spec(gmap, _expand_strategy(strategies[0]))

    best_plan = Plan()
    best_score = float("-inf")
    for s in strategies:
        candidate = build_from_spec(gmap, _expand_strategy(s))
        sim = simulate(candidate, gmap, ticks=_INTERNAL_EVAL_TICKS)
        sb = score_plan(sim)
        if sb.total > best_score:
            best_score = sb.total
            best_plan = candidate
    return best_plan
