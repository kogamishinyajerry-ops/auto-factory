"""Factory layout planner — the live edit surface.

iterate.py (autonomous mutation loop) rewrites the CONFIG block below
between the AUTORESEARCH markers. Hand-editing the block is fine; the
loop will pick up whatever's there as its starting state.

CONFIG schema:
    {
        "strategies": [
            {"lane_configs":   <key into LANE_CONFIG_SETS>,
             "miner_pick":     "closest_y" | "leftmost" | "min_route",
             "max_route_dist": int or None},
            ...     # one or more strategies
        ]
    }

If "strategies" has one entry, factory_plan == that single strategy.
If it has multiple entries, factory_plan internally builds and scores
each one and returns whichever yields the highest score (portfolio
pattern, same idea as v3_greedy_search but the membership is mutable).

Score = widgets_per_minute
      - 0.500   * belt_crossings
      - 0.0005  * sum_energy_per_tick * ticks
      - 0.050   * total_building_cost
      - 0.001   * congestion_ticks
"""

from __future__ import annotations

from auto_factory import GameMap, Plan, score_plan, simulate

from plans.v3_greedy_search import LANE_CONFIG_SETS, _build_candidate


# === AUTORESEARCH CONFIG START ===
# (iterate.py rewrites between these markers; hand-editing is fine too)
CONFIG = {
    "strategies": [
        {
            "lane_configs": "all17",
            "miner_pick": "closest_y",
            "max_route_dist": None
        },
        {
            "lane_configs": "shift_down",
            "miner_pick": "leftmost",
            "max_route_dist": 25
        },
        {
            "lane_configs": "all17",
            "miner_pick": "min_route",
            "max_route_dist": 25
        },
        {
            "lane_configs": "shift_down",
            "miner_pick": "closest_y",
            "max_route_dist": 25
        },
        {
            "lane_configs": "rev",
            "miner_pick": "min_route",
            "max_route_dist": 12
        }
    ]
}
# === AUTORESEARCH CONFIG END ===

# Ticks used for in-planner scoring when the portfolio has >1 strategy.
# Match eval.py default so the picked strategy is the one that's actually
# best at the metric the harness will judge it on.
_INTERNAL_EVAL_TICKS = 600


def plan(gmap: GameMap) -> Plan:
    strategies = CONFIG["strategies"]
    if len(strategies) == 1:
        s = strategies[0]
        return _build_candidate(
            gmap,
            LANE_CONFIG_SETS[s["lane_configs"]],
            s["miner_pick"],
            s["max_route_dist"],
        )

    best_plan = Plan()
    best_score = float("-inf")
    for s in strategies:
        candidate = _build_candidate(
            gmap,
            LANE_CONFIG_SETS[s["lane_configs"]],
            s["miner_pick"],
            s["max_route_dist"],
        )
        sim = simulate(candidate, gmap, ticks=_INTERNAL_EVAL_TICKS)
        sb = score_plan(sim)
        if sb.total > best_score:
            best_score = sb.total
            best_plan = candidate
    return best_plan
