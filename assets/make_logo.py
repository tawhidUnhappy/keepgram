"""keepgram's logo, as an Android adaptive icon (Material 3 Expressive look):
a 108-unit canvas, the launcher shows the middle 72 under its own mask shape,
and everything that matters sits inside the 66-unit safe circle.

    python assets/make_logo.py    -> the .svg layers here, and the .png files
                                     too if cairosvg is installed

Layers: background (colour), foreground (the cookie shape, folder and
bookmark), monochrome (one colour, for Android's themed icons). The .png files
are the layers put together under a squircle (logo.png, the README's) and a
circle (avatar.png, for a Telegram channel or profile photo)."""

from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

BG = "#2F3DBF"
COOKIE = "#4A5BE6"
FOLDER_BACK = "#B9C3FF"
FOLDER_FRONT = "#EEF0FF"
RIBBON = "#FF8A65"
RIBBON_SHADE = "#E8704C"


def cookie(cx=54.0, cy=54.0, radius=29.5, depth=2.3, lobes=9, steps=360) -> str:
    """Material's scalloped "cookie" shape: a circle with soft lobes."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        r = radius + depth * math.cos(lobes * t)
        pts.append(f"{cx + r * math.sin(t):.2f},{cy - r * math.cos(t):.2f}")
    return "M" + " L".join(pts) + " Z"


FOLDER_BACK_PATH = (
    "M33,41 a4,4 0 0 1 4,-4 h10 a3,3 0 0 1 2.1,0.9 l3,3 h19.9 a4,4 0 0 1 4,4 v24.1 a4,4 0 0 1 -4,4 h-35"
    " a4,4 0 0 1 -4,-4 z"
)
FOLDER_FRONT_PATH = "M33,51 a4,4 0 0 1 4,-4 h35 a4,4 0 0 1 4,4 v18 a4,4 0 0 1 -4,4 h-35 a4,4 0 0 1 -4,-4 z"
RIBBON_PATH = "M60,34 a2.5,2.5 0 0 1 2.5,-2.5 h6 a2.5,2.5 0 0 1 2.5,2.5 v26 l-5.5,-4.2 l-5.5,4.2 z"


def svg(body: str, size=108, view="0 0 108 108") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="{view}">\n'
            f"{body}\n</svg>\n")


def background() -> str:
    return f'  <rect width="108" height="108" fill="{BG}"/>'


def foreground() -> str:
    return "\n".join([
        f'  <path d="{cookie()}" fill="{COOKIE}"/>',
        f'  <path d="{FOLDER_BACK_PATH}" fill="{FOLDER_BACK}"/>',
        f'  <path d="{FOLDER_FRONT_PATH}" fill="{FOLDER_FRONT}"/>',
        # the ribbon's fold, where it goes over the front of the folder
        f'  <path d="M60,47 h11 v2 h-11 z" fill="{RIBBON_SHADE}"/>',
        f'  <path d="{RIBBON_PATH}" fill="{RIBBON}"/>',
        f'  <path d="M60,47 h11 v1.6 h-11 z" fill="{RIBBON_SHADE}"/>',
    ])


def monochrome() -> str:
    """One colour, for themed icons: the folder with the bookmark cut out of it
    (even-odd fill), its top still standing above the folder."""
    return "\n".join([
        f'  <path d="{FOLDER_BACK_PATH} {RIBBON_PATH}" fill="#000" fill-rule="evenodd"/>',
        f'  <path d="{FOLDER_FRONT_PATH} {RIBBON_PATH}" fill="#000" fill-rule="evenodd"/>',
        # the part of the bookmark above the folder, solid
        '  <path d="M60,34 a2.5,2.5 0 0 1 2.5,-2.5 h6 a2.5,2.5 0 0 1 2.5,2.5 v3 h-11 z" fill="#000"/>',
    ])


def squircle(cx=54.0, cy=54.0, r=36.0, n=4.6, steps=240) -> str:
    """A superellipse, close to the mask Pixel launchers use."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = cx + r * math.copysign(abs(c) ** (2 / n), c)
        y = cy + r * math.copysign(abs(s) ** (2 / n), s)
        pts.append(f"{x:.2f},{y:.2f}")
    return "M" + " L".join(pts) + " Z"


def composed(shape: str, size: int) -> str:
    """Both layers under a mask, cropped to the 72 units a launcher shows."""
    return svg(
        f'  <defs><clipPath id="m"><path d="{shape}"/></clipPath></defs>\n'
        f'  <g clip-path="url(#m)">\n{background()}\n{foreground()}\n  </g>',
        size=size, view="18 18 72 72",
    )


def main() -> None:
    files = {
        "ic_launcher_background.svg": svg(background()),
        "ic_launcher_foreground.svg": svg(foreground()),
        "ic_launcher_monochrome.svg": svg(monochrome()),
        "logo.svg": composed(squircle(), 512),
        "avatar.svg": composed("M54,18 a36,36 0 1 1 0,72 a36,36 0 1 1 0,-72 z", 640),
    }
    for name, text in files.items():
        (HERE / name).write_text(text, encoding="utf-8")
    try:
        import cairosvg
    except ImportError:
        print("SVGs written; install cairosvg for the PNGs")
        return
    cairosvg.svg2png(bytestring=files["logo.svg"].encode(), write_to=str(HERE / "logo.png"), output_width=512,
                     output_height=512)
    cairosvg.svg2png(bytestring=files["avatar.svg"].encode(), write_to=str(HERE / "avatar.png"), output_width=640,
                     output_height=640)
    cairosvg.svg2png(bytestring=files["logo.svg"].encode(), write_to=str(HERE / "icon-48.png"), output_width=48,
                     output_height=48)
    print("SVGs and PNGs written")


if __name__ == "__main__":
    main()
