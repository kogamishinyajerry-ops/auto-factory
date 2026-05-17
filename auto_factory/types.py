from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Resource(str, Enum):
    IRON = "iron"
    COPPER = "copper"
    COAL = "coal"
    OIL = "oil"


class BuildingType(str, Enum):
    MINER = "M"
    BELT = "B"
    SMELTER = "S"
    ASSEMBLER = "A"
    OUTPUT = "O"


class Direction(str, Enum):
    N = "N"
    E = "E"
    S = "S"
    W = "W"

    @property
    def delta(self) -> Tuple[int, int]:
        return {
            Direction.N: (0, -1),
            Direction.E: (1, 0),
            Direction.S: (0, 1),
            Direction.W: (-1, 0),
        }[self]


BUILDING_COST: Dict[BuildingType, float] = {
    BuildingType.MINER: 10.0,
    BuildingType.BELT: 1.0,
    BuildingType.SMELTER: 20.0,
    BuildingType.ASSEMBLER: 30.0,
    BuildingType.OUTPUT: 5.0,
}

BUILDING_ENERGY: Dict[BuildingType, float] = {
    BuildingType.MINER: 1.0,
    BuildingType.BELT: 0.1,
    BuildingType.SMELTER: 2.0,
    BuildingType.ASSEMBLER: 3.0,
    BuildingType.OUTPUT: 0.0,
}


@dataclass(frozen=True)
class Building:
    type: BuildingType
    x: int
    y: int
    direction: Optional[Direction] = None  # belts only

    def __post_init__(self) -> None:
        if self.type == BuildingType.BELT and self.direction is None:
            raise ValueError(f"belt at ({self.x},{self.y}) needs a direction")

    @property
    def pos(self) -> Tuple[int, int]:
        return (self.x, self.y)


@dataclass
class GameMap:
    width: int
    height: int
    resources: Dict[Tuple[int, int], Resource]
    seed: int

    def resource_at(self, x: int, y: int) -> Optional[Resource]:
        return self.resources.get((x, y))

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height


@dataclass
class Plan:
    buildings: List[Building] = field(default_factory=list)

    def add(self, b: Building) -> None:
        self.buildings.append(b)
