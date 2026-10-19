"""Draw the Tokie app icon and write assets/tokie.png + assets/tokie.ico (build-time only, needs Pillow).

    python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

BG, EDGE = (22, 24, 35, 255), (45, 50, 73, 255)
BARS = ((255, 155, 113, 255), (143, 123, 255, 255), (106, 165, 255, 255))  # Claude / accent / Codex
SIZES = [16, 24, 32, 48, 64, 128, 256]
BIG = 1024  # draw large, then downscale so small sizes stay smooth


def draw_icon():
    im = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = int(BIG * 0.04)
    d.rounded_rectangle((m, m, BIG - m, BIG - m), radius=int(BIG * 0.22), fill=BG, outline=EDGE, width=int(BIG * 0.02))
    bar_w, gap, base = int(BIG * 0.15), int(BIG * 0.07), int(BIG * 0.76)
    heights = (0.30, 0.52, 0.38)
    x0 = (BIG - (3 * bar_w + 2 * gap)) // 2
    for i, (h, color) in enumerate(zip(heights, BARS)):
        x = x0 + i * (bar_w + gap)
        d.rounded_rectangle((x, base - int(BIG * h), x + bar_w, base), radius=bar_w // 2, fill=color)
    # little sparkle above the tallest bar
    cx, cy, r = x0 + bar_w + gap + bar_w // 2, int(BIG * 0.145), int(BIG * 0.04)
    d.polygon([(cx, cy - 2 * r), (cx + r // 2, cy - r // 2), (cx + 2 * r, cy), (cx + r // 2, cy + r // 2),
               (cx, cy + 2 * r), (cx - r // 2, cy + r // 2), (cx - 2 * r, cy), (cx - r // 2, cy - r // 2)],
              fill=(255, 233, 168, 255))
    return im


def main():
    out = Path(__file__).resolve().parent.parent / "assets"
    out.mkdir(exist_ok=True)
    im = draw_icon()
    im.resize((256, 256), Image.LANCZOS).save(out / "tokie.png")
    im.resize((256, 256), Image.LANCZOS).save(out / "tokie.ico", sizes=[(s, s) for s in SIZES])
    print("wrote", out / "tokie.png", "and", out / "tokie.ico")


if __name__ == "__main__":
    main()
