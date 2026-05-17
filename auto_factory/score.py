from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .sim import SimResult


# Scoring weights (tunable; baseline rewards throughput, penalises bloat).
# Tuned so a fully-connected baseline (~20 widgets/min, ~25 buildings, modest
# congestion) lands slightly positive while disconnected/broken plans go
# clearly negative. Claude can iterate up from a positive baseline.
W_THROUGHPUT = 1.0
W_CROSSING = 0.5
W_ENERGY = 0.0005     # energy_total accumulates over ticks; keep weight small
W_BUILDING = 0.05
W_CONGESTION = 0.001  # per congested belt-tick


@dataclass
class ScoreBreakdown:
    total: float
    throughput: float
    crossing_pen: float
    energy_pen: float
    building_pen: float
    congestion_pen: float
    valid: bool
    reason: str

    def to_dict(self) -> Dict[str, float | str | bool]:
        return {
            "total": round(self.total, 3),
            "throughput": round(self.throughput, 3),
            "crossing_pen": round(self.crossing_pen, 3),
            "energy_pen": round(self.energy_pen, 3),
            "building_pen": round(self.building_pen, 3),
            "congestion_pen": round(self.congestion_pen, 3),
            "valid": self.valid,
            "reason": self.reason,
        }


def score_plan(sim: SimResult) -> ScoreBreakdown:
    if not sim.valid:
        return ScoreBreakdown(
            total=-1000.0,
            throughput=0.0,
            crossing_pen=0.0,
            energy_pen=0.0,
            building_pen=0.0,
            congestion_pen=0.0,
            valid=False,
            reason=sim.reason,
        )

    throughput = W_THROUGHPUT * sim.widgets_per_minute
    crossing_pen = W_CROSSING * sim.crossings
    energy_pen = W_ENERGY * sim.energy_total
    building_pen = W_BUILDING * sim.building_cost
    congestion_pen = W_CONGESTION * sim.congestion

    total = throughput - crossing_pen - energy_pen - building_pen - congestion_pen
    return ScoreBreakdown(
        total=total,
        throughput=throughput,
        crossing_pen=crossing_pen,
        energy_pen=energy_pen,
        building_pen=building_pen,
        congestion_pen=congestion_pen,
        valid=True,
        reason="",
    )
