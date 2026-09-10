"""
Render an MP4 video of the operator dashboard: NORMAL -> ATTACK -> RECOVERED.

Same look as the web dashboard (app/frontend/index.html), driven by the real
plant simulation. Uses a constant-size canvas (the status bar is always present,
green when nominal / red during the attack) so the frames encode cleanly to
video, and steps the plant in sub-second increments so values move smoothly.

    python -m demo.make_dashboard_video --out demo/dashboard_demo.mp4
"""
from __future__ import annotations

import argparse

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sim.plant import Plant
from sim.register_map import SENSORS

# palette (matches the web dashboard) --------------------------------------
BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (201, 209, 217)
DIM = (139, 148, 158)
OK = (63, 185, 80)
OK_BG = (18, 33, 22)
BAD = (248, 81, 73)
BAD_BG = (40, 22, 24)
CYAN = (57, 197, 207)

W = 1000
MARGIN = 24
GAP = 14
COLS = 4
CARD_H = 104
HEADER_H = 62
BANNER_H = 46
FONT = "C:/Windows/Fonts/segoeui.ttf"
FONTB = "C:/Windows/Fonts/segoeuib.ttf"


def f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONTB if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def render(state: dict, attack: bool) -> Image.Image:
    card_w = (W - 2 * MARGIN - (COLS - 1) * GAP) // COLS
    rows = (len(SENSORS) + COLS - 1) // COLS
    grid_top = HEADER_H + 22 + BANNER_H + 16 + 30
    height = grid_top + rows * (CARD_H + GAP) + MARGIN

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)

    # header ----------------------------------------------------------------
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.line([0, HEADER_H, W, HEADER_H], fill=BORDER, width=1)
    d.text((MARGIN, 20), "Water-Treatment ICS  —  Operator Dashboard",
           fill=FG, font=f(20, True))
    label = "ATTACK IN PROGRESS" if attack else "Normal"
    color = BAD if attack else OK
    tw = d.textlength(label, font=f(15, True))
    cx = W - MARGIN - tw - 22
    d.ellipse([cx, 27, cx + 12, 39], fill=color)
    d.text((cx + 20, 20), label, fill=color, font=f(15, True))

    # status banner (always present -> constant canvas height) ---------------
    y = HEADER_H + 22
    if attack:
        p = next(s for s in SENSORS if s.tag == "LIT101")
        v = state["LIT101"]
        d.rounded_rectangle([MARGIN, y, W - MARGIN, y + BANNER_H], 8, BAD_BG, BAD, 1)
        msg = (f"\U0001F6A8  LIT101 (Raw water tank level) = {v:.2f} {p.unit} "
               f"outside safe band [{p.lo:g}..{p.hi:g}]")
        d.text((MARGIN + 16, y + 13), msg, fill=(255, 179, 174), font=f(15, True))
    else:
        d.rounded_rectangle([MARGIN, y, W - MARGIN, y + BANNER_H], 8, OK_BG, OK, 1)
        d.text((MARGIN + 16, y + 13), "\u2714  All systems nominal — no active alerts",
               fill=(126, 231, 135), font=f(15, True))
    y += BANNER_H + 16

    d.text((MARGIN, y), "SENSORS", fill=CYAN, font=f(13, True))
    y += 30

    # sensor cards ----------------------------------------------------------
    for i, p in enumerate(SENSORS):
        r, c = divmod(i, COLS)
        x0 = MARGIN + c * (card_w + GAP)
        y0 = y + r * (CARD_H + GAP)
        v = state[p.tag]
        ok = p.lo <= v <= p.hi
        d.rounded_rectangle([x0, y0, x0 + card_w, y0 + CARD_H], 9,
                            BAD_BG if not ok else PANEL, BAD if not ok else BORDER, 1)
        d.text((x0 + 14, y0 + 12), p.tag, fill=FG, font=f(14, True))
        d.text((x0 + 14, y0 + 33), p.description[:30], fill=DIM, font=f(11))
        d.text((x0 + 14, y0 + 52), f"{v:.2f}", fill=BAD if not ok else FG, font=f(26, True))
        vw = d.textlength(f"{v:.2f}", font=f(26, True))
        d.text((x0 + 16 + vw, y0 + 64), f" {p.unit}", fill=DIM, font=f(12))
        d.text((x0 + 14, y0 + 84), f"safe [{p.lo:g}..{p.hi:g}]", fill=DIM, font=f(11))

    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo/dashboard_demo.mp4")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--substeps", type=int, default=4, help="frames per sim-second")
    args = ap.parse_args()

    plant = Plant(seed=42)
    for _ in range(20):
        plant.step(1.0)

    def soft_plc(s):
        s["MV101"] = 0 if s["LIT101"] > 900 else 1
        s["P101"] = 1 if s["LIT101"] > 500 else 0
        s["P201"] = 1 if s["AIT202"] < 6.8 else 0
        s["P203"] = 1 if s["AIT202"] > 7.8 else 0

    dt = 1.0 / args.substeps
    frames = []

    def phase(seconds, attack, spoof=None):
        for _ in range(seconds * args.substeps):
            soft_plc(plant.state)
            plant.step(dt)
            snap = plant.snapshot()
            if spoof:
                snap.update(spoof)
            frames.append(render(snap, attack))

    phase(6, attack=False)                             # normal operation
    phase(10, attack=True, spoof={"LIT101": 1180.0})   # sustained spoof attack
    phase(6, attack=False)                             # cleared / recovered

    # hold first & last frames ~1s for readability
    hold = args.fps
    seq = [frames[0]] * hold + frames + [frames[-1]] * hold

    writer = imageio.get_writer(args.out, fps=args.fps, codec="libx264",
                                quality=8, macro_block_size=None)
    for im in seq:
        writer.append_data(np.asarray(im.convert("RGB")))
    writer.close()
    print(f"wrote {args.out}  ({len(seq)} frames @ {args.fps}fps, {frames[0].size[0]}x{frames[0].size[1]})")


if __name__ == "__main__":
    main()
