"""keepgram's file thumbnails: the picture Telegram shows beside a file keepgram
sends as a file (a video kept as a file, a PDF, an archive, a part ...). Photos
sent as photos and videos sent as videos keep Telegram's own preview.

Same look as the logo (make_logo.py), the Android 17 / Material 3 Expressive
style: a tonal colour per kind, the scalloped cookie shape, one bold symbol, and
keepgram's bookmark in the corner.

    python assets/make_thumbs.py   -> assets/thumbs/<kind>.svg, and
                                      keepgram/thumbs/<kind>.jpg (needs cairosvg + Pillow)

Telegram takes a JPEG of at most 320x320 and 200 KB as a file's thumbnail."""

from __future__ import annotations

import io
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG_DIR = HERE / "thumbs"
JPG_DIR = HERE.parent / "keepgram" / "thumbs"
BRAND = "#2F3DBF"  # the bookmark: keepgram's indigo

# kind: (background, cookie, symbol)
COLOURS = {
    "video": ("#FFD8E4", "#FFB0C8", "#7D2950"),
    "audio": ("#EADDFF", "#D0BCFF", "#4F378B"),
    "image": ("#C4EED0", "#9ED8AE", "#0F5223"),
    "archive": ("#FFE08C", "#F5C64A", "#5C4300"),
    "document": ("#D3E4FF", "#A8C8FF", "#0B3F7A"),
    "app": ("#B8F0E8", "#86D6CC", "#00504A"),
    "part": ("#FFDBCB", "#FFB693", "#7A3000"),
    "other": ("#DEE0FF", "#B9C3FF", "#2F3DBF"),
}


def cookie(cx=54.0, cy=54.0, radius=33.0, depth=2.6, lobes=9, steps=360) -> str:
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        r = radius + depth * math.cos(lobes * t)
        pts.append(f"{cx + r * math.sin(t):.2f},{cy - r * math.cos(t):.2f}")
    return "M" + " L".join(pts) + " Z"


def symbol(kind: str, c: str, bg: str) -> str:
    """The symbol, drawn in a 108-unit box around (54, 54)."""
    if kind == "video":  # a rounded play triangle
        return (f'<path d="M45,37 L73,54 L45,71 Z" fill="{c}" stroke="{c}" stroke-width="8" '
                f'stroke-linejoin="round"/>')
    if kind == "audio":  # two notes on one beam
        return (f'<path d="M41.5,37 L74.5,30 V40 L41.5,47 Z" fill="{c}" stroke="{c}" stroke-width="2" '
                f'stroke-linejoin="round"/>'
                f'<rect x="41.5" y="40" width="5" height="30" fill="{c}"/>'
                f'<rect x="69.5" y="33" width="5" height="31" fill="{c}"/>'
                f'<ellipse cx="38.5" cy="70" rx="7.5" ry="6" fill="{c}"/>'
                f'<ellipse cx="66.5" cy="64" rx="7.5" ry="6" fill="{c}"/>')
    if kind == "image":  # a frame, hills and a sun
        return (f'<rect x="33" y="36" width="42" height="36" rx="7" fill="{c}"/>'
                f'<path d="M37,68 L49,53 L57,62 L62,57 L71,68 Z" fill="{bg}"/>'
                f'<circle cx="64" cy="46" r="4.5" fill="{bg}"/>')
    if kind == "archive":  # a box with a zip down the middle
        teeth = "".join(f'<rect x="{51 if i % 2 else 55}" y="{47 + i * 5}" width="4" height="4" rx="1" fill="{bg}"/>'
                        for i in range(4))
        return (f'<rect x="33" y="40" width="42" height="34" rx="6" fill="{c}"/>'
                f'<rect x="30" y="33" width="48" height="11" rx="5" fill="{c}"/>'
                f'<rect x="30" y="43" width="48" height="2.5" fill="{bg}"/>' + teeth)
    if kind == "document":  # a page with a folded corner and lines
        return (f'<path d="M38,32 H60 L72,44 V72 a4,4 0 0 1 -4,4 H40 a4,4 0 0 1 -4,-4 V36 a4,4 0 0 1 4,-4 Z" '
                f'fill="{c}"/>'
                f'<path d="M60,32 V40 a4,4 0 0 0 4,4 H72 Z" fill="{bg}" opacity="0.55"/>'
                + "".join(f'<rect x="43" y="{50 + i * 7}" width="{22 if i < 2 else 14}" height="3.4" rx="1.7" '
                          f'fill="{bg}"/>' for i in range(3)))
    if kind == "app":  # four rounded tiles
        return "".join(f'<rect x="{x}" y="{y}" width="18" height="18" rx="6" fill="{c}"/>'
                       for x in (34, 56) for y in (34, 56))
    if kind == "part":  # a puzzle piece: one part of a file
        return (f'<path d="M35,46 H46 a6,6 0 1 1 12,0 H69 V57 a6,6 0 1 1 0,12 V74 H35 Z" fill="{c}" '
                f'stroke="{c}" stroke-width="3" stroke-linejoin="round"/>')
    # other: a plain page
    return (f'<path d="M38,32 H60 L72,44 V72 a4,4 0 0 1 -4,4 H40 a4,4 0 0 1 -4,-4 V36 a4,4 0 0 1 4,-4 Z" '
            f'fill="{c}"/><path d="M60,32 V40 a4,4 0 0 0 4,4 H72 Z" fill="{bg}" opacity="0.55"/>')


def thumb(kind: str) -> str:
    bg, ck, c = COLOURS[kind]
    bookmark = f'<path d="M80,0 h14 v20 l-7,-5.5 l-7,5.5 z" fill="{BRAND}"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 108 108">'
            f'<rect width="108" height="108" fill="{bg}"/><path d="{cookie()}" fill="{ck}"/>'
            f"{symbol(kind, c, ck)}{bookmark}</svg>\n")


def main() -> None:
    SVG_DIR.mkdir(exist_ok=True)
    JPG_DIR.mkdir(exist_ok=True)
    for kind in COLOURS:
        (SVG_DIR / f"{kind}.svg").write_text(thumb(kind), encoding="utf-8")
    try:
        import cairosvg
        from PIL import Image
    except ImportError:
        print("SVGs written; install cairosvg and Pillow for the JPEGs keepgram sends")
        return
    for kind in COLOURS:
        png = cairosvg.svg2png(bytestring=thumb(kind).encode(), output_width=320, output_height=320)
        out = JPG_DIR / f"{kind}.jpg"
        Image.open(io.BytesIO(png)).convert("RGB").save(out, "JPEG", quality=90, optimize=True)
        assert out.stat().st_size < 200_000, out
    print("SVGs and JPEGs written")


if __name__ == "__main__":
    main()
