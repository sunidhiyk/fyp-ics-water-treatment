"""
Render an animated GIF of the live plant monitor for reports/slides.

Runs the simulator in-process, captures N frames of the register table over
time, renders each frame as a terminal-style image (dark background, monospace),
and stitches them into a looping GIF. To make the animation visually show the
detection concept, one sensor is nudged out of band partway through so the
``!!`` out-of-band flag lights up (a preview of what an attack triggers).

    python -m demo.make_gif --out demo/plant_demo.gif --frames 16
"""
from __future__ import annotations

import argparse

from PIL import Image, ImageDraw, ImageFont

from sim.plant import Plant
from sim.register_map import SENSORS, ACTUATORS

# -- palette (a calm dark terminal theme) -----------------------------------
BG = (13, 17, 23)
FG = (201, 209, 217)
DIM = (110, 118, 129)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
AMBER = (210, 153, 34)
CYAN = (57, 197, 207)
TITLE = (88, 166, 255)

FONT_PATH = "C:/Windows/Fonts/consola.ttf"
FONT_BOLD = "C:/Windows/Fonts/consolab.ttf"
FS = 20
LH = 26                      # line height
PAD = 24
WIDTH = 720
ACT_LABEL = {0: "OFF", 1: "ON", 2: "TRANS"}


def _font(bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, FS)
    except OSError:
        return ImageFont.load_default()


def render_frame(state: dict, injected: bool) -> Image.Image:
    n_lines = 6 + len(SENSORS) + 3 + (len(ACTUATORS) + 1) // 2 + 2
    height = PAD * 2 + n_lines * LH
    img = Image.new("RGB", (WIDTH, height), BG)
    d = ImageDraw.Draw(img)
    f, fb = _font(), _font(bold=True)
    y = PAD

    def line(text, color=FG, font=f, x=PAD):
        nonlocal y
        d.text((x, y), text, fill=color, font=font)
        y += LH

    line("Water-Treatment Plant  —  live (Modbus TCP :5020)", TITLE, fb)
    line("─" * 46, DIM)
    banner = "STATUS: ATTACK — LIT101 spoofed out of band" if injected else \
             "STATUS: normal operation"
    line(banner, RED if injected else GREEN, fb)
    y += LH // 2
    line("SENSORS", CYAN, fb)
    line(f"  {'tag':8}{'value':>10} {'unit':7}{'safe band':>15}", DIM)
    for p in SENSORS:
        v = state[p.tag]
        ok = p.lo <= v <= p.hi
        flag = "  " if ok else "!!"
        color = FG if ok else RED
        d.text((PAD, y), flag, fill=RED, font=fb)
        d.text((PAD + 3 * 12, y),
               f"{p.tag:8}{v:>10.2f} {p.unit:7}[{p.lo:g}..{p.hi:g}]",
               fill=color, font=f)
        y += LH
    y += LH // 2
    line("ACTUATORS", CYAN, fb)
    # two per row to keep it compact
    acts = list(ACTUATORS)
    for i in range(0, len(acts), 2):
        row = ""
        for p in acts[i:i + 2]:
            st = ACT_LABEL.get(int(round(state[p.tag])), "?")
            row += f"  {p.tag:7}{st:5}"
        line(row, FG)
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo/plant_demo.gif")
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--step-secs", type=float, default=1.0,
                    help="sim seconds advanced per captured frame")
    ap.add_argument("--fps", type=float, default=2.0)
    args = ap.parse_args()

    plant = Plant(seed=42)
    # settle the process into steady state first
    for _ in range(20):
        plant.step(1.0)

    frames: list[Image.Image] = []
    inject_at = args.frames // 2
    for i in range(args.frames):
        # simple soft-PLC so the process stays alive during capture
        s = plant.state
        s["MV101"] = 0 if s["LIT101"] > 900 else 1
        s["P101"] = 1 if s["LIT101"] > 500 else 0
        s["P201"] = 1 if s["AIT202"] < 6.8 else 0
        s["P203"] = 1 if s["AIT202"] > 7.8 else 0
        plant.step(args.step_secs)

        injected = i >= inject_at
        snap = plant.snapshot()
        if injected:
            snap["LIT101"] = 1180.0   # spoofed level: above safe band -> !! lights up
        frames.append(render_frame(snap, injected))

    duration = int(1000 / args.fps)
    frames[0].save(args.out, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, optimize=True)
    print(f"wrote {args.out}  ({len(frames)} frames, {frames[0].size[0]}x{frames[0].size[1]})")


if __name__ == "__main__":
    main()
