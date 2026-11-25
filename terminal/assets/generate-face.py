#!/usr/bin/env python3
"""Generate MAD Terminal theme assets from MAD's own avatar.

Source of the face: the @MADx402 X profile picture, fetched live
from the X API (profile_image_url), 400x400 JPEG. NEVER a human face:
MAD's face is the flaming auditor in the avatar, and that is the only
likeness that goes in this terminal.

Outputs (all under assets/):
  mad-face.txt        plain grayscale ASCII, banner size (48 cols)
  mad-face-mini.txt   plain grayscale ASCII, error size (20 cols)
  mad-face-color.txt  ANSI 256-color ASCII, banner size
  palette.json        dominant colors (hex) + nearest xterm-256 codes

Regenerate: python3 assets/generate-face.py
"""
import json
import os
from PIL import Image, ImageOps, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "mad-avatar.jpg")
# The ASCII is drawn from the face crop (the round flaming head),
# not the full illustration - the lab background drowns the face
# at terminal resolution. The crop is MAD's face, nothing else.
FACE_SRC = os.path.join(HERE, "mad-face-crop.jpg")
RAMP = " .:-=+*#%@"  # dark -> light


def to_ascii(im, cols, color=False):
    w, h = im.size
    # Terminal cells are ~2x as tall as wide; squash vertically.
    rows = max(1, int(h * cols / w / 2.0))
    small = im.resize((cols, rows), Image.LANCZOS)
    # The avatar is mostly mid-tone reds: stretch the contrast so the
    # dark eyes and frown separate from the bright face.
    gray = ImageOps.autocontrast(small.convert("L"), cutoff=1)
    px = gray.load()
    lines = []
    if not color:
        for y in range(rows):
            lines.append("".join(
                RAMP[min(len(RAMP) - 1, px[x, y] * len(RAMP) // 256)]
                for x in range(cols)))
        return "\n".join(lines)
    rgb = small.convert("RGB")
    cp = rgb.load()
    for y in range(rows):
        line = ""
        for x in range(cols):
            r, g, b = cp[x, y]
            lum = px[x, y]
            code = rgb_to_256(r, g, b)
            ch = RAMP[min(len(RAMP) - 1, lum * len(RAMP) // 256)]
            line += "\x1b[38;5;%dm%s" % (code, ch)
        lines.append(line + "\x1b[0m")
    return "\n".join(lines)


def rgb_to_256(r, g, b):
    # Nearest xterm-256 cube colour (plus greys for near-grey pixels).
    if abs(r - g) < 12 and abs(g - b) < 12:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 23)
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) \
        + round(b / 255 * 5)


def palette(im, n=6):
    q = im.convert("RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    out = []
    for count, idx in counts:
        r, g, b = pal[idx * 3:idx * 3 + 3]
        out.append({"hex": "#%02x%02x%02x" % (r, g, b),
                    "xterm256": rgb_to_256(r, g, b),
                    "share_pct": round(100 * count / (im.size[0] * im.size[1]), 1)})
    return out


def to_halfblock(im, cols):
    """Terminal-pixel rendering: each cell is U+2580 with the top
    pixel as foreground and the bottom pixel as background, so one
    cell carries two rows of the face. At 48 cols this reads as the
    face; the character-ramp ASCII is the plain fallback."""
    w, h = im.size
    rows = max(1, int(h * cols / w))  # cells, each 2 px tall
    small = im.resize((cols, rows * 2), Image.LANCZOS).convert("RGB")
    px = small.load()
    lines = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            top = px[x, y * 2]
            bot = px[x, y * 2 + 1]
            line += ("\x1b[38;5;%dm\x1b[48;5;%dm\u2580" % (
                rgb_to_256(*top), rgb_to_256(*bot)))
        lines.append(line + "\x1b[0m")
    return "\n".join(lines)


def preview_halfblock(text, path, cell_w=10, cell_h=18):
    """Render half-block ANSI text to a PNG by drawing each cell as
    two stacked colour rectangles (top fg, bottom bg)."""
    import re
    lines = text.split("\n")
    cols = max(len(re.findall("▀", l)) for l in lines)
    img = Image.new("RGB", (cols * cell_w + 20, len(lines) * cell_h + 20),
                    (12, 4, 5))
    d = ImageDraw.Draw(img)
    for yi, line in enumerate(lines):
        fg = bg = (255, 255, 255)
        xi = 0
        esc = "\x1b"
        for tok in re.split("(" + esc + r"\[[0-9;]*m|▀)", line):
            m = re.match(esc + r"\[38;5;(\d+)m", tok)
            if m:
                fg = xterm_to_rgb(int(m.group(1)))
                continue
            m = re.match(esc + r"\[48;5;(\d+)m", tok)
            if m:
                bg = xterm_to_rgb(int(m.group(1)))
                continue
            if tok == "▀":
                x0 = 10 + xi * cell_w
                y0 = 10 + yi * cell_h
                d.rectangle([x0, y0, x0 + cell_w, y0 + cell_h // 2],
                            fill=fg)
                d.rectangle([x0, y0 + cell_h // 2, x0 + cell_w,
                             y0 + cell_h], fill=bg)
                xi += 1
    img.save(path)


def xterm_to_rgb(n):
    if n < 16:
        base = [(0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
                (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
                (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
                (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
        return base[n]
    if n < 232:
        n -= 16
        r, g, b = n // 36, (n % 36) // 6, n % 6
        f = lambda v: 0 if v == 0 else 55 + 40 * v
        return (f(r), f(g), f(b))
    v = 8 + 10 * (n - 232)
    return (v, v, v)


def main():
    face = Image.open(FACE_SRC).convert("RGB")
    im = Image.open(SRC).convert("RGB")
    full = to_ascii(face, 48)
    mini = to_ascii(face, 20)
    color = to_halfblock(face, 48)
    color_mini = to_halfblock(face, 16)
    pal = palette(im)
    with open(os.path.join(HERE, "mad-face.txt"), "w") as f:
        f.write(full + "\n")
    with open(os.path.join(HERE, "mad-face-mini.txt"), "w") as f:
        f.write(mini + "\n")
    with open(os.path.join(HERE, "mad-face-color.txt"), "w") as f:
        f.write(color + "\n")
    with open(os.path.join(HERE, "mad-face-mini-color.txt"), "w") as f:
        f.write(color_mini + "\n")
    with open(os.path.join(HERE, "palette.json"), "w") as f:
        json.dump({"source": "MAD @MADx402 X avatar (pbs.twimg.com, "
                             "400x400, fetched 2026-11-24)",
                   "palette": pal}, f, indent=2)
    preview_halfblock(color, os.path.join(HERE, "mad-face-preview.png"))
    preview_halfblock(color_mini,
                      os.path.join(HERE, "mad-face-mini-preview.png"))
    print("face: %d lines, mini: %d lines, palette:" % (
        full.count("\n") + 1, mini.count("\n") + 1))
    for c in pal:
        print("  %s xterm-%d (%.1f%%)" % (c["hex"], c["xterm256"],
                                           c["share_pct"]))


if __name__ == "__main__":
    main()
