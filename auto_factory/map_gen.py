from __future__ import annotations

import random
from typing import Tuple

from .types import GameMap, Resource


def generate_map(seed: int, width: int = 20, height: int = 15) -> GameMap:
    """Deterministic procedural map. Seed -> resource patches."""
    rng = random.Random(seed)
    resources: dict[Tuple[int, int], Resource] = {}

    num_patches = rng.randint(4, 8)
    rtypes = list(Resource)
    # Guarantee at least one iron and one copper so widgets are buildable.
    forced = [Resource.IRON, Resource.COPPER]
    for i in range(num_patches):
        rtype = forced[i] if i < len(forced) else rng.choice(rtypes)
        cx = rng.randint(2, width - 3)
        cy = rng.randint(2, height - 3)
        patch = rng.randint(4, 9)
        cells = [(cx, cy)]
        for _ in range(patch - 1):
            ox, oy = rng.choice(cells)
            dx, dy = rng.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])
            nx, ny = ox + dx, oy + dy
            if 0 <= nx < width and 0 <= ny < height:
                cells.append((nx, ny))
        for c in cells:
            resources.setdefault(c, rtype)
    return GameMap(width=width, height=height, resources=resources, seed=seed)
