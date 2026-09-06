"""
Render an animated GIF that mirrors the web operator dashboard, walking through
NORMAL -> ATTACK (LIT101 spoofed out of band) -> CLEARED. Styled to match
app/frontend/index.html so it reads as "the dashboard" in slides.

Driven by the real plant simulation (sim/plant.py); the attack phase injects a
held false LIT101 reading exactly as the live "Inject attack" button does.

    python -m demo.make_dashboard_gif --out demo/dashboard_demo.gif
"""
from __future__ import annotations

import argparse

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
BAD = (248, 81, 73)
BAD_BG = (40, 22, 24)
ACCENT = (88, 166, 255)
CYAN = (57, 197, 207)

W = 1000
MARGIN = 24
GAP = 14
COLS = 4
CARD_H = 104
HEADER_H = 62
FONT = "C:/Windows/Fonts/segoeui.ttf"
FONTB = "C:/Windows/Fonts/segoeuib.ttf"


def f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONTB if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def _round_rect(d, box, radius, fill, outline, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def render(state: dict, attack: bool) -> Image.Image:
    card_w = (W - 2 * MARGIN - (COLS - 1) * GAP) // COLS
    rows = (len(SENSORS) + COLS - 1) // COLS
    alert_h = 46
    grid_top = HEADER_H + 20 + (alert_h + 16 if attack else 0) + 30
    height = grid_top + rows * (CARD_H + GAP) + MARGIN

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)

    # header ----------------------------------------------------------------
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.line([0, HEADER_H, W, HEADER_H], fill=BORDER, width=1)
    d.text((MARGIN, 20), "Water-Treatment ICS  —  Operator Dashboard",
           fill=FG, font=f(20, True))
    # status pill
    label = "ATTACK IN PROGRESS" if attack else "Normal"
    color = BAD if attack else OK
    tw = d.textlength(label, font=f(15, True))
    cx = W - MARGIN - tw - 22
    d.ellipse([cx, 27, cx + 12, 39], fill=color)
    d.text((cx + 20, 20), label, fill=color, font=f(15, True))

    y = HEADER_H + 22

    # alert banner ----------------------------------------------------------
    if attack:
        p = next(s for s in SENSORS if s.tag == "LIT101")
        v = state["LIT101"]
        _round_rect(d, [MARGIN, y, W - MARGIN, y + alert_h], 8, BAD_BG, BAD, 1)
        msg = (f"\U0001F6A8  LIT101 (Raw water tank level) = {v:.2f} {p.unit} "
               f"outside safe band [{p.lo:g}..{p.hi:g}]")
        d.text((MARGIN + 16, y + 13), msg, fill=(255, 179, 174), font=f(15, True))
        y += alert_h + 16

    d.text((MARGIN, y), "SENSORS", fill=CYAN, font=f(13, True))
    y += 30

    # sensor cards ----------------------------------------------------------
    for i, p in enumerate(SENSORS):
        r, c = divmod(i, COLS)
        x0 = MARGIN + c * (card_w + GAP)
        y0 = y + r * (CARD_H + GAP)
        v = state[p.tag]
        ok = p.lo <= v <= p.hi
        _round_rect(d, [x0, y0, x0 + card_w, y0 + CARD_H], 9,
                    BAD_BG if not ok else PANEL, BAD if not ok else BORDER, 1)
        d.text((x0 + 14, y0 + 12), p.tag, fill=FG, font=f(14, True))
        desc = p.description[:30]
        d.text((x0 + 14, y0 + 33), desc, fill=DIM, font=f(11))
        val_color = BAD if not ok else FG
        d.text((x0 + 14, y0 + 52), f"{v:.2f}", fill=val_color, font=f(26, True))
        vw = d.textlength(f"{v:.2f}", font=f(26, True))
        d.text((x0 + 16 + vw, y0 + 64), f" {p.unit}", fill=DIM, font=f(12))
        d.text((x0 + 14, y0 + 84), f"safe [{p.lo:g}..{p.hi:g}]", fill=DIM, font=f(11))

    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo/dashboard_demo.gif")
    ap.add_argument("--fps", type=float, default=2.0)
    args = ap.parse_args()

    plant = Plant(seed=42)
    for _ in range(20):          # settle to steady state
        plant.step(1.0)

    def soft_plc(s):
        s["MV101"] = 0 if s["LIT101"] > 900 else 1
        s["P101"] = 1 if s["LIT101"] > 500 else 0
        s["P201"] = 1 if s["AIT202"] < 6.8 else 0
        s["P203"] = 1 if s["AIT202"] > 7.8 else 0

    frames: list[Image.Image] = []

    def capture(n, attack, spoof=None):
        for _ in range(n):
            soft_plc(plant.state)
            plant.step(1.0)
            snap = plant.snapshot()
            if spoof:
                snap.update(spoof)
            frames.append(render(snap, attack))

    capture(5, attack=False)                          # normal
    capture(6, attack=True, spoof={"LIT101": 1180.0})  # attack held
    capture(4, attack=False)                          # cleared / recovered

    # hold the final normal + peak attack frames a touch longer for readability
    order = frames[:1] * 2 + frames + frames[-1:] * 2
    duration = int(1000 / args.fps)
    order[0].save(args.out, save_all=True, append_images=order[1:],
                  duration=duration, loop=0, optimize=True)
    print(f"wrote {args.out}  ({len(order)} frames, {frames[0].size[0]}x{frames[0].size[1]})")


if __name__ == "__main__":
    main()
