"""Archived planner variants.

The live planner is at /Users/Zhuanz/Desktop/auto-factory/factory_plan.py
(or whatever you pass via --planner). This package keeps known-good baselines
around so you can A/B against them with bench.py.

Conventions:
  - Each module exports `plan(gmap: GameMap) -> Plan`.
  - Variants are versioned vN_<short_description>.py.
  - Shared routing helpers live in auto_factory.routing (re-exported as
    `auto_factory.lay_belts`).
"""

__all__ = ["v0_naive", "v1_multi_lane"]
