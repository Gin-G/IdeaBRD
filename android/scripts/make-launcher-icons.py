#!/usr/bin/env python3
"""Regenerate the launcher icons from the board's own logo.

    python3 android/scripts/make-launcher-icons.py

The app icon used to be a lightbulb drawn by hand in a vector drawable, which
had nothing to do with the board it launches. This renders the real logo
instead, from the same file the web app serves, so the two can't drift.

The output is an adaptive icon: `ic_launcher_foreground.png` is a 108dp canvas
with the logo sized to 72dp in the middle, and the background is a flat colour.
Android crops the outer 18dp for parallax and then applies the launcher's own
mask — a circle on Pixel, a squircle elsewhere — so the logo's rounded frame
lands just inside whatever shape the phone draws. The legacy `ic_launcher.png`
and `ic_launcher_round.png` are pre-masked for the same reason, even though
minSdk 26 means every device we ship to reads the adaptive icon.

Needs Pillow: pip install pillow
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "frontend/static/IdeaBRD-logo.png"
RES = ROOT / "android/app/src/main/res"

# Dark navy, the same #0f172a the shell paints behind the web app.
BACKGROUND = (15, 23, 42, 255)

# dp of the 108dp canvas the artwork occupies. 72dp is the mask's own size:
# the logo then fills a squircle edge to edge, and a circle trims the corners
# of its frame — which reads as deliberate, because the frame is round already.
ART_DP = 72

DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def artwork() -> Image.Image:
    """The logo, cropped to its own ink — the PNG has transparent margins."""
    logo = Image.open(SOURCE).convert("RGBA")
    return logo.crop(logo.getchannel("A").getbbox())


def foreground(art: Image.Image, size: int) -> Image.Image:
    """A 108dp adaptive-icon foreground layer, transparent behind the logo."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    target = round(size * ART_DP / 108)
    scale = target / max(art.size)
    scaled = art.resize(
        (round(art.width * scale), round(art.height * scale)), Image.LANCZOS
    )
    canvas.alpha_composite(
        scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2)
    )
    return canvas


def legacy(art: Image.Image, size: int, round_icon: bool) -> Image.Image:
    """A pre-masked icon for launchers that don't read the adaptive one."""
    # The legacy icon is the mask's worth of the canvas, so the same artwork
    # scaled by 72/108 of the adaptive canvas is simply the full square here.
    canvas = Image.new("RGBA", (size, size), BACKGROUND)
    scale = size / max(art.size)
    scaled = art.resize(
        (round(art.width * scale), round(art.height * scale)), Image.LANCZOS
    )
    canvas.alpha_composite(
        scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2)
    )

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    if round_icon:
        draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    else:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=255)
    canvas.putalpha(mask)
    return canvas


def main() -> None:
    art = artwork()
    for density, factor in DENSITIES.items():
        out = RES / f"mipmap-{density}"
        out.mkdir(parents=True, exist_ok=True)
        foreground(art, round(108 * factor)).save(out / "ic_launcher_foreground.png")
        legacy(art, round(48 * factor), False).save(out / "ic_launcher.png")
        legacy(art, round(48 * factor), True).save(out / "ic_launcher_round.png")
        print(f"{out.relative_to(ROOT)}: foreground, square, round")


if __name__ == "__main__":
    main()
