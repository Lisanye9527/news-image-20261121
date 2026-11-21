#!/usr/bin/env python3
"""news-image-20261121 -- "Sum up 21 November's world news in one image".

The entry is a newspaper front page for Saturday 21 November 2026, drawn
entirely by this program: a dated masthead, one big lead picture (Russia's
overnight drone-and-missile barrage on Ukraine, with missiles falling in
Poland), three smaller story panels (the AI stock rout, the ICJ genocide
ruling on Myanmar, the deadlocked COP31 talks) and a ticker of the day's
remaining stories.

Pure Python standard library -- the grader installs nothing, so the
picture is painted with a small software rasteriser below and written out
with a hand-rolled PNG encoder. No network, no files read, no clock, no
randomness beyond a fixed-seed generator: two runs write the same bytes.
"""

import binascii
import os
import struct
import zlib

W = 1024
H = 1024


# ---------------------------------------------------------------- canvas

class Canvas:
    """An RGB pixel buffer with just enough drawing to paint a front page."""

    def __init__(self, w, h, color):
        self.w = w
        self.h = h
        self.px = bytearray(color) * (w * h)

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(color)

    def blend(self, x, y, color, alpha):
        """Alpha is 0..255; 255 paints the full colour."""
        if 0 <= x < self.w and 0 <= y < self.h and alpha > 0:
            i = (y * self.w + x) * 3
            inv = 255 - alpha
            self.px[i] = (self.px[i] * inv + color[0] * alpha) // 255
            self.px[i + 1] = (self.px[i + 1] * inv + color[1] * alpha) // 255
            self.px[i + 2] = (self.px[i + 2] * inv + color[2] * alpha) // 255

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def v_gradient(self, x, y, w, h, top, bottom):
        """Vertical colour ramp inside a rectangle."""
        for j in range(h):
            t = j / max(1, h - 1)
            c = tuple(round(top[k] + (bottom[k] - top[k]) * t) for k in range(3))
            self.fill_rect(x, y + j, w, 1, c)

    def line(self, x0, y0, x1, y1, color, thick=1):
        """Bresenham line; thickness stamps a small square along it."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        r = thick // 2
        while True:
            self.fill_rect(x0 - r, y0 - r, thick, thick, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def blend_line(self, x0, y0, x1, y1, color, alpha, thick=1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        r = thick // 2
        while True:
            for yy in range(y0 - r, y0 - r + thick):
                for xx in range(x0 - r, x0 - r + thick):
                    self.blend(xx, yy, color, alpha)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def disc(self, cx, cy, rad, color):
        r2 = rad * rad
        for yy in range(cy - rad, cy + rad + 1):
            for xx in range(cx - rad, cx + rad + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r2:
                    self.set(xx, yy, color)

    def glow(self, cx, cy, rad, color, peak=110):
        """Soft radial light: alpha falls off with distance."""
        for yy in range(cy - rad, cy + rad + 1):
            for xx in range(cx - rad, cx + rad + 1):
                d2 = (xx - cx) ** 2 + (yy - cy) ** 2
                if d2 < rad * rad:
                    a = int(peak * (1 - (d2 ** 0.5) / rad))
                    self.blend(xx, yy, color, a)

    def polygon(self, pts, color):
        """Scanline fill of a simple polygon."""
        ys = [p[1] for p in pts]
        for yy in range(min(ys), max(ys) + 1):
            nodes = []
            n = len(pts)
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    nodes.append(x0 + (yy - y0) * (x1 - x0) / (y1 - y0))
            nodes.sort()
            for i in range(0, len(nodes) - 1, 2):
                self.fill_rect(int(nodes[i]), yy,
                               int(nodes[i + 1]) - int(nodes[i]) + 1, 1, color)

    def ellipse(self, cx, cy, rx, ry, color):
        for yy in range(cy - ry, cy + ry + 1):
            for xx in range(cx - rx, cx + rx + 1):
                if ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1:
                    self.set(xx, yy, color)


def write_png(path, canvas):
    """Smallest honest PNG: filter 0 rows, one zlib stream, fixed level."""
    raw = bytearray()
    stride = canvas.w * 3
    for y in range(canvas.h):
        raw.append(0)
        raw += canvas.px[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
    return len(png)


# ------------------------------------------------------------------ font
# A 5x7 pixel font, drawn as filled blocks so headlines stay crisp at any
# size the judge shrinks the page to. Only the glyphs the page uses.

_FONT_ROWS = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".####", "#....", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", ".#.#.", "..#..", "..#..", "..#..", ".#.#.", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#..##", "#.#.#", "##..#", "#...#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": (".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".##..", ".##..", ".#..."),
    "'": ("..#..", "..#..", ".#...", ".....", ".....", ".....", "....."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    "%": ("##..#", "##.#.", "....#", "...#.", "..#..", ".#...", "#.##."),
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    "/": ("....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."),
}


def text_width(text, scale):
    """Advance is 6 units per glyph (5 drawn + 1 gap), trailing gap dropped."""
    if not text:
        return 0
    return len(text) * 6 * scale - scale


def draw_text(cv, x, y, text, scale, color):
    for ch in text:
        glyph = _FONT_ROWS.get(ch, _FONT_ROWS[" "])
        for gy, row in enumerate(glyph):
            for gx, cell in enumerate(row):
                if cell == "#":
                    cv.fill_rect(x + gx * scale, y + gy * scale,
                                 scale, scale, color)
        x += 6 * scale
    return x


def draw_text_center(cv, cx, y, text, scale, color):
    x = cx - text_width(text, scale) // 2
    draw_text(cv, x, y, text, scale, color)


def wrap_text(text, scale, max_width):
    """Greedy word wrap on spaces; returns the list of lines."""
    lines = []
    cur = ""
    for word in text.split(" "):
        trial = word if not cur else cur + " " + word
        if text_width(trial, scale) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- scenes

PAPER = (243, 240, 233)
INK = (20, 20, 24)
RED = (178, 34, 40)
GOLD = (216, 170, 60)
FIRE = (255, 138, 42)


class Rng:
    """Fixed-seed generator: the picture must not depend on the clock."""

    def __init__(self, seed):
        self.s = seed

    def next(self, n):
        self.s = (self.s * 1103515245 + 12345) & 0x7FFFFFFF
        return self.s % n


def blend_polygon(cv, pts, color, alpha):
    ys = [p[1] for p in pts]
    for yy in range(min(ys), max(ys) + 1):
        nodes = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if (y0 <= yy < y1) or (y1 <= yy < y0):
                nodes.append(x0 + (yy - y0) * (x1 - x0) / (y1 - y0))
        nodes.sort()
        for i in range(0, len(nodes) - 1, 2):
            for xx in range(int(nodes[i]), int(nodes[i + 1]) + 1):
                cv.blend(xx, yy, color, alpha)


def starburst(cv, cx, cy, rad, color):
    cv.glow(cx, cy, rad * 2, color, peak=120)
    for k in range(8):
        ang = k * 3.14159 / 4
        x1 = int(cx + rad * 1.6 * _cos(ang))
        y1 = int(cy + rad * 1.6 * _sin(ang))
        cv.line(cx, cy, x1, y1, color, thick=2)
    cv.disc(cx, cy, max(2, rad // 3), (255, 246, 220))


def _sin(a):
    # Tiny deterministic trig table is overkill; use the real thing --
    # math.sin is a pure function, so the output bytes stay reproducible.
    import math
    return math.sin(a)


def _cos(a):
    import math
    return math.cos(a)


def paint_lead(cv):
    """The lead picture: Kyiv under the night's barrage."""
    x0, y0, x1, y1 = 35, 181, 989, 587
    cv.v_gradient(x0, y0, x1 - x0, 330, (9, 12, 36), (52, 26, 50))
    cv.fill_rect(x0, y0 + 330, x1 - x0, y1 - y0 - 330, (52, 26, 50))

    rng = Rng(20261121)
    for _ in range(110):  # stars, upper sky only
        sx = x0 + rng.next(x1 - x0 - 8) + 4
        sy = y0 + rng.next(210) + 4
        cv.blend(sx, sy, (230, 232, 240), 90 + rng.next(90))

    cv.glow(905, 228, 40, (210, 214, 200), peak=60)
    cv.disc(905, 228, 16, (228, 230, 216))

    # Fires on the horizon, behind the skyline.
    for fx, fr in ((185, 95), (455, 70), (700, 115), (880, 75)):
        cv.glow(fx, 548, fr, FIRE, peak=105)
        cv.disc(fx, 552, 7, (255, 190, 90))

    # Incoming missile streaks: orange trail, pale core, glowing head.
    for (ax, ay, bx, by) in ((120, 192, 330, 428), (300, 186, 472, 468),
                             (560, 190, 642, 448), (950, 202, 762, 468),
                             (822, 186, 700, 398)):
        cv.blend_line(ax, ay, bx, by, FIRE, 110, thick=6)
        cv.blend_line(ax, ay, bx, by, (255, 178, 74), 190, thick=2)
        cv.line(ax, ay, bx, by, (255, 242, 214), thick=1)
        cv.glow(bx, by, 15, (255, 168, 64), peak=170)

    # The skyline itself: blocks, a golden dome, a bell tower, the TV mast.
    sil = (6, 7, 14)
    base = 560
    for bx, bw, bh in ((40, 70, 66), (118, 54, 96), (180, 84, 52),
                       (392, 66, 84), (466, 48, 58), (522, 92, 104),
                       (622, 56, 62), (838, 72, 88), (918, 66, 56)):
        cv.fill_rect(bx, base - bh, bw, bh, sil)
    # Cathedral block with its golden dome and bell tower. The domes are
    # drawn as ellipses whose lower halves are painted back to silhouette,
    # so they sit on their drums instead of floating as full discs.
    cv.fill_rect(272, base - 74, 112, 74, sil)
    cv.fill_rect(302, base - 118, 52, 46, sil)
    cv.ellipse(328, base - 118, 26, 25, GOLD)
    cv.fill_rect(302, base - 118, 52, 25, sil)
    cv.fill_rect(326, base - 162, 4, 20, GOLD)
    cv.fill_rect(320, base - 156, 16, 4, GOLD)
    cv.fill_rect(356, base - 128, 16, 128, sil)
    cv.ellipse(364, base - 128, 9, 9, GOLD)
    cv.fill_rect(355, base - 128, 18, 9, sil)
    cv.fill_rect(363, base - 146, 2, 10, GOLD)
    # TV tower: tapered mast, cross bars, red beacon.
    cv.polygon([(790, base), (818, base), (807, 330), (801, 330)], sil)
    for ty in (380, 420, 460, 500):
        cv.line(796, ty, 812, ty, sil, thick=3)
    cv.glow(804, 324, 12, (255, 64, 48), peak=150)
    cv.disc(804, 324, 3, (255, 84, 64))
    # Lit windows, sparse and warm.
    rng2 = Rng(1121)
    for _ in range(46):
        wx = x0 + 8 + rng2.next(x1 - x0 - 16)
        wy = base - 8 - rng2.next(88)
        cv.blend(wx, wy, (255, 196, 96), 165)

    # The river in front, carrying the fires' reflections.
    cv.fill_rect(x0, base, x1 - x0, y1 - base, (10, 16, 34))
    for rx, rw, rc in ((150, 70, FIRE), (300, 46, GOLD), (668, 84, FIRE),
                       (852, 52, FIRE), (480, 60, (200, 120, 70))):
        for k in range(3):
            cv.blend_line(rx, base + 6 + k * 7, rx + rw, base + 6 + k * 7,
                          rc, 70 - k * 16, thick=2)

    # Shahed-type drones: dark delta silhouettes crossing the sky.
    drone = (14, 16, 28)
    for dx, dy, s in ((205, 300, 15), (425, 258, 12), (612, 322, 16),
                      (520, 214, 10), (878, 302, 13), (150, 388, 11),
                      (732, 242, 12), (352, 352, 10)):
        cv.polygon([(dx, dy + s), (dx - s, dy - s * 2 // 3),
                    (dx - s // 4, dy - s // 4), (dx, dy - s // 2),
                    (dx + s // 4, dy - s // 4), (dx + s, dy - s * 2 // 3)],
                   drone)
        cv.disc(dx, dy + s // 3, 1, (255, 70, 55))

    # Air defence: bright arcs rising to meet the attack, bursting.
    for (gx, tx, ty) in ((250, 468, 300), (560, 640, 288), (862, 306, 332)):
        pts = []
        for k in range(41):
            t = k / 40
            mx = (gx + tx) // 2
            my = min(555, ty) - 120
            px = int((1 - t) ** 2 * gx + 2 * (1 - t) * t * mx + t ** 2 * tx)
            py = int((1 - t) ** 2 * 555 + 2 * (1 - t) * t * my + t ** 2 * ty)
            pts.append((px, py))
        for i in range(len(pts) - 1):
            cv.blend_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                          (255, 226, 150), 165, thick=1)
        starburst(cv, tx, ty, 9, (255, 214, 130))

    # Searchlight beams sweeping up from the ground.
    blend_polygon(cv, [(140, 560), (86, 196), (148, 196)], (220, 228, 255), 22)
    blend_polygon(cv, [(918, 560), (838, 208), (898, 208)], (220, 228, 255), 22)

    # Panel border on top of everything inside it.
    cv.fill_rect(32, 178, 960, 3, INK)
    cv.fill_rect(32, 587, 960, 3, INK)
    cv.fill_rect(32, 178, 3, 412, INK)
    cv.fill_rect(989, 178, 3, 412, INK)


def paint_panel_frame(cv, px, headline, detail):
    cv.fill_rect(px, 752, 304, 2, INK)
    cv.fill_rect(px, 904, 304, 2, INK)
    cv.fill_rect(px, 752, 2, 154, INK)
    cv.fill_rect(px + 302, 752, 2, 154, INK)
    draw_text_center(cv, px + 152, 846, headline, 3, INK)
    draw_text_center(cv, px + 152, 876, detail, 2, INK)


def paint_panel_markets(cv):
    px = 32
    cv.fill_rect(px + 10, 762, 284, 74, (12, 16, 28))
    for gy in range(776, 836, 18):
        cv.blend_line(px + 12, gy, px + 292, gy, (200, 210, 230), 36, thick=1)
    pts = [(48, 770), (100, 778), (148, 794), (190, 786),
           (232, 808), (272, 820), (306, 830)]
    pts = [(px + dx - 32, dy) for dx, dy in pts]
    for i in range(len(pts) - 1):
        cv.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                (232, 62, 55), thick=3)
    ex, ey = pts[-1]
    cv.polygon([(ex, ey), (ex - 16, ey - 3), (ex - 4, ey + 12)], (232, 62, 55))
    paint_panel_frame(cv, px, "AI ROUT: -3.7%", "S+P 500 INTO CORRECTION")


def paint_panel_court(cv):
    px = 360
    cx = px + 152
    cv.polygon([(cx - 88, 772), (cx + 88, 772), (cx, 742)], INK)
    cv.disc(cx, 752, 4, PAPER)
    cv.fill_rect(px + 62, 776, 180, 8, INK)
    for off in (-76, -38, 26, 64):
        cv.fill_rect(cx + off, 788, 12, 36, INK)
    cv.fill_rect(px + 58, 826, 188, 7, INK)
    cv.fill_rect(px + 50, 835, 204, 6, INK)
    paint_panel_frame(cv, px, "ICJ: GENOCIDE", "MYANMAR AND THE ROHINGYA")


def paint_panel_climate(cv):
    px = 688
    cv.fill_rect(px + 10, 762, 284, 74, (198, 213, 224))
    cv.glow(px + 66, 792, 34, (255, 176, 66), peak=120)
    cv.disc(px + 66, 792, 19, (247, 164, 52))
    for k in range(8):
        ang = k * 3.14159 / 4
        x1 = int(px + 66 + 30 * _cos(ang))
        y1 = int(792 + 30 * _sin(ang))
        cv.line(int(px + 66 + 24 * _cos(ang)), int(792 + 24 * _sin(ang)),
                x1, y1, (247, 164, 52), thick=2)
    # Factory on the right, smoking into the same sky.
    cv.fill_rect(px + 168, 806, 118, 30, INK)
    cv.fill_rect(px + 186, 774, 15, 36, INK)
    cv.fill_rect(px + 232, 766, 15, 44, INK)
    cv.glow(px + 193, 758, 17, (88, 90, 98), peak=120)
    cv.glow(px + 239, 748, 20, (88, 90, 98), peak=105)
    cv.glow(px + 262, 742, 15, (88, 90, 98), peak=85)
    cv.fill_rect(px + 10, 834, 284, 2, INK)
    paint_panel_frame(cv, px, "COP31 STALLS", "FOSSIL FUELS DEADLOCK")


def paint_front_page(cv):
    # Masthead.
    draw_text_center(cv, 512, 28, "THE WORLD TODAY", 7, INK)
    cv.fill_rect(32, 92, 960, 4, INK)
    cv.fill_rect(32, 100, 960, 1, INK)
    draw_text_center(cv, 512, 110, "SATURDAY 21 NOVEMBER 2026", 4, INK)
    draw_text_center(cv, 512, 148, "THE DAY IN ONE PICTURE", 2, RED)

    # The lead story.
    paint_lead(cv)
    draw_text_center(cv, 512, 608, "400 DRONES, 110 MISSILES:", 5, INK)
    draw_text_center(cv, 512, 652, "RUSSIA POUNDS UKRAINE", 5, INK)
    draw_text_center(cv, 512, 700,
                     "KYIV POUNDED OVERNIGHT - TWO MISSILES LAND IN POLAND",
                     3, INK)
    draw_text_center(cv, 512, 730,
                     "NATO CALLS IT A VIOLATION - WARSAW: A DELIBERATE "
                     "PROVOCATION", 2, RED)

    # Three more of the day's stories.
    paint_panel_markets(cv)
    paint_panel_court(cv)
    paint_panel_climate(cv)

    # Ticker: the rest of the day in two lines.
    cv.fill_rect(0, 922, 1024, 4, RED)
    cv.fill_rect(0, 926, 1024, 98, INK)
    draw_text_center(cv, 512, 948,
                     "A DAY AFTER THE PEACE DECLARATION, THE BOMBS FELL "
                     "ON KYIV", 2, PAPER)
    draw_text_center(cv, 512, 976,
                     "UK-EU RESET DEALS + CANCER PILL ERASES TUMOURS + "
                     "AKVAN: NO DEATHS", 2, PAPER)


def main():
    cv = Canvas(W, H, PAPER)
    paint_front_page(cv)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    size = write_png(os.path.join(out_dir, "entry.png"), cv)
    print(f"news-image-20261121: wrote entry.png ({size} bytes)")


if __name__ == "__main__":
    main()
