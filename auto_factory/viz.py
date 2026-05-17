from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from .types import Building, BuildingType, Direction, GameMap, Plan, Resource

RESOURCE_GLYPH = {
    Resource.IRON: "i",
    Resource.COPPER: "c",
    Resource.COAL: "k",
    Resource.OIL: "o",
}

# Foreground color per building type (RGB).
BUILDING_COLOR = {
    BuildingType.MINER: (60, 60, 60),
    BuildingType.BELT: (255, 215, 0),
    BuildingType.SMELTER: (200, 80, 30),
    BuildingType.ASSEMBLER: (30, 90, 200),
    BuildingType.OUTPUT: (180, 30, 180),
}

RESOURCE_COLOR = {
    Resource.IRON: (180, 180, 200),
    Resource.COPPER: (210, 130, 70),
    Resource.COAL: (40, 40, 40),
    Resource.OIL: (90, 70, 50),
}

# Direction → arrow glyph (used both ASCII + PNG)
ARROW = {
    Direction.N: "^",
    Direction.E: ">",
    Direction.S: "v",
    Direction.W: "<",
}


def _bld_map(plan: Plan) -> Dict[Tuple[int, int], Building]:
    return {b.pos: b for b in plan.buildings}


def render_ascii(plan: Plan, gmap: GameMap) -> str:
    bld = _bld_map(plan)
    lines = []
    header = "    " + "".join(f"{x % 10}" for x in range(gmap.width))
    lines.append(header)
    lines.append("   +" + "-" * gmap.width + "+")
    for y in range(gmap.height):
        row = []
        for x in range(gmap.width):
            b = bld.get((x, y))
            if b is not None:
                if b.type == BuildingType.BELT and b.direction is not None:
                    row.append(ARROW[b.direction])
                else:
                    row.append(b.type.value)
            else:
                r = gmap.resource_at(x, y)
                row.append(RESOURCE_GLYPH[r] if r is not None else ".")
        lines.append(f"{y:>2} |" + "".join(row) + "|")
    lines.append("   +" + "-" * gmap.width + "+")
    return "\n".join(lines)


def render_png(
    plan: Plan,
    gmap: GameMap,
    path: Path,
    title: Optional[str] = None,
    cell_px: int = 32,
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return  # silently skip if PIL not installed

    bld = _bld_map(plan)
    margin = 16
    title_h = 28 if title else 0
    W = margin * 2 + gmap.width * cell_px
    H = margin * 2 + title_h + gmap.height * cell_px

    img = Image.new("RGB", (W, H), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", size=max(10, cell_px // 2)
        )
        title_font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", size=16
        )
    except OSError:
        font = ImageFont.load_default()
        title_font = font

    if title:
        draw.text((margin, margin // 2), title, fill=(20, 20, 20), font=title_font)

    base_y = margin + title_h

    # background: resource shading
    for (x, y), r in gmap.resources.items():
        col = RESOURCE_COLOR[r]
        px = margin + x * cell_px
        py = base_y + y * cell_px
        draw.rectangle([px, py, px + cell_px - 1, py + cell_px - 1], fill=col)

    # grid lines
    for x in range(gmap.width + 1):
        gx = margin + x * cell_px
        draw.line(
            [(gx, base_y), (gx, base_y + gmap.height * cell_px)],
            fill=(200, 200, 200),
            width=1,
        )
    for y in range(gmap.height + 1):
        gy = base_y + y * cell_px
        draw.line(
            [(margin, gy), (margin + gmap.width * cell_px, gy)],
            fill=(200, 200, 200),
            width=1,
        )

    # buildings
    for pos, b in bld.items():
        x, y = pos
        px = margin + x * cell_px
        py = base_y + y * cell_px
        color = BUILDING_COLOR[b.type]
        if b.type == BuildingType.BELT:
            # draw thinner belt rectangle
            inset = max(2, cell_px // 8)
            draw.rectangle(
                [px + inset, py + inset, px + cell_px - inset, py + cell_px - inset],
                fill=color,
                outline=(80, 60, 0),
            )
            glyph = ARROW[b.direction] if b.direction else "?"
        else:
            draw.rectangle(
                [px + 1, py + 1, px + cell_px - 2, py + cell_px - 2],
                fill=color,
                outline=(0, 0, 0),
            )
            glyph = b.type.value

        # contrasting glyph
        text_color = (255, 255, 255) if b.type != BuildingType.BELT else (0, 0, 0)
        try:
            bbox = draw.textbbox((0, 0), glyph, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            tw, th = font.getsize(glyph)
        draw.text(
            (px + (cell_px - tw) // 2, py + (cell_px - th) // 2 - 2),
            glyph,
            fill=text_color,
            font=font,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
