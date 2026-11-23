#!/usr/bin/env python3
"""Seamless background tiles for kitty, one pattern per kind of work.

Each tile is the theme's own background with only the pattern's lines in the kind's colour. Shapes
are also drawn shifted by one tile in every direction, so the tile repeats without seams.

    python3 patterns.py OUTDIR [--light]

writes <pattern>.svg and <pattern>.png (via rsvg-convert) for each pattern.

The software pattern's icons are from Simple Icons (https://simpleicons.org, CC0), in patterns/icons.
"""
import math
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICONS = HERE / "patterns" / "icons"

PATTERNS = {  # pattern -> (kind, dark-theme line colour, light-theme line colour)
    "pin-grid": ("pcb", "#4a3560", "#d9c3e6"),
    "hex-dump": ("firmware", "#2f5a3c", "#bfdcc4"),
    "icon-graph": ("software", "#33476b", "#c2d1ec"),
    "iso-blocks": ("cad", "#5c4a22", "#e8d39a"),
}
DARK_BG, LIGHT_BG = "#1d2021", "#faf3d9"


def tile(size, bg, style, *layers, extra=""):
    """An SVG tile: each layer is drawn again at the eight neighbouring offsets, so shapes crossing an
    edge come back in on the other side. `extra` is drawn as is, above the layers."""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{size}" height="{size}" viewBox="0 0 {size} {size}"><style>{style}</style>'
           f'<rect width="{size}" height="{size}" fill="{bg}"/>']
    for n, body in enumerate(layers):
        out.append(f'<g id="l{n}">{body}</g>')
        out += [f'<use xlink:href="#l{n}" x="{dx}" y="{dy}"/>'
                for dx in (-size, 0, size) for dy in (-size, 0, size) if dx or dy]
    out.append(extra + "</svg>")
    return "".join(out)


def wrapd(a, b, size):
    """Shortest offset from a to b on a periodic axis."""
    return (b - a + size / 2) % size - size / 2


def mix(color, other, t):
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


# ---------------------------------------------------------------- firmware: hex dump

def hex_dump(color, bg, light, seed=3):
    rnd = random.Random(seed)
    T, col_w, row_h = 480, 20, 20
    parts = []
    for r in range(T // row_h):
        c, on = 0, rnd.random() < .5
        while c < T // col_w:  # runs of bytes and gaps: scattered blocks, not a wall of text
            run = rnd.randint(2, 7) if on else rnd.randint(2, 9)
            if on:
                for i in range(c, min(c + run, T // col_w)):
                    op = .55 if rnd.random() < .85 else 1
                    parts.append(f'<text x="{i * col_w + 1}" y="{r * row_h + 14}" opacity="{op}">'
                                 f'{rnd.randrange(256):02X}</text>')
            c += run
            on = not on
    style = f'text{{fill:{color};font:600 11px "JetBrainsMono Nerd Font Mono","DejaVu Sans Mono",monospace}}'
    return tile(T, bg, style, "".join(parts))


# ---------------------------------------------------------------- PCB: chip footprints on a pin grid

def pin_grid(color, bg, light, seed=5):
    rnd = random.Random(seed)
    T, P = 480, 16
    N = T // P
    used = set()
    parts = []
    chips = 0
    for _ in range(400):
        w, h = rnd.randint(5, 11), rnd.randint(5, 11)
        x0, y0 = rnd.randrange(N), rnd.randrange(N)
        area = {((x0 + i) % N, (y0 + j) % N) for i in range(-2, w + 2) for j in range(-2, h + 2)}
        if area & used:
            continue
        used |= area
        chips += 1
        X, Y = x0 * P, y0 * P
        if rnd.random() < .6:  # BGA: a grid of balls, sometimes with the middle empty
            hole = rnd.random() < .5
            for i in range(w):
                for j in range(h):
                    if (hole and 2 <= i < w - 2 and 2 <= j < h - 2) or rnd.random() < .08:
                        continue
                    parts.append(f'<circle cx="{X + i * P + P / 2}" cy="{Y + j * P + P / 2}" r="2.6" class="ball"/>')
            parts.append(f'<rect x="{X - 5}" y="{Y - 5}" width="{w * P + 10}" height="{h * P + 10}" rx="4" class="body"/>')
            parts.append(f'<circle cx="{X + 1}" cy="{Y + 1}" r="1.8" class="ball"/>')
        else:  # QFP: a body with pins out of every side
            bx, by, bw, bh = X + 4, Y + 4, w * P - 8, h * P - 8
            parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="3" class="body"/>')
            parts.append(f'<circle cx="{bx + 8}" cy="{by + 8}" r="2.4" class="body"/>')
            for i in range(int((bw - 10) // 8) + 1):
                px = bx + 6 + i * 8
                parts.append(f'<line x1="{px}" y1="{by - 7}" x2="{px}" y2="{by}" class="pin"/>'
                             f'<line x1="{px}" y1="{by + bh}" x2="{px}" y2="{by + bh + 7}" class="pin"/>')
            for j in range(int((bh - 10) // 8) + 1):
                py = by + 6 + j * 8
                parts.append(f'<line x1="{bx - 7}" y1="{py}" x2="{bx}" y2="{py}" class="pin"/>'
                             f'<line x1="{bx + bw}" y1="{py}" x2="{bx + bw + 7}" y2="{py}" class="pin"/>')
        if chips >= 7:
            break
    for i in range(N):  # the faint dot matrix everywhere else
        for j in range(N):
            if (i, j) not in used:
                parts.append(f'<circle cx="{i * P + P / 2}" cy="{j * P + P / 2}" r="1" class="dot"/>')
    style = (f'.ball{{fill:{color}}}.dot{{fill:{color};opacity:.55}}'
             f'.body{{fill:none;stroke:{color};stroke-width:1.4}}.pin{{stroke:{color};stroke-width:2.2}}')
    return tile(T, bg, style, "".join(parts))


# ---------------------------------------------------------------- software: a network of project icons

ICON_ORDER = ["linux", "git", "python", "kde", "claude", "archlinux", "github", "gnubash", "kicad",
              "espressif", "c", "freecad"]


def icon_graph(color, bg, light, seed=21):
    rnd = random.Random(seed)
    T = 720
    pts = []
    for _ in range(6000):  # Poisson-disk points on the torus
        p = (rnd.uniform(0, T), rnd.uniform(0, T))
        if all(math.hypot(wrapd(p[0], q[0], T), wrapd(p[1], q[1], T)) > 62 for q in pts):
            pts.append(p)
    dist = lambda p, q: math.hypot(wrapd(p[0], q[0], T), wrapd(p[1], q[1], T))
    icons = sorted(f.stem for f in ICONS.glob("*.svg"))
    icons = [s for s in ICON_ORDER if s in icons] + [s for s in icons if s not in ICON_ORDER]
    hubs = [0]  # icon nodes: spread out, each as far as possible from the others
    while len(hubs) < len(icons):
        hubs.append(max((i for i in range(len(pts)) if i not in hubs), key=lambda i: min(dist(pts[i], pts[h]) for h in hubs)))
    edges = set()
    for i, p in enumerate(pts):
        near = sorted((dist(p, q), j) for j, q in enumerate(pts) if j != i)
        for _, j in near[:3 if i in hubs else rnd.choice([2, 2, 3])]:
            edges.add((min(i, j), max(i, j)))
    lines = []
    for i, j in sorted(edges):
        (ax, ay), (bx, by) = pts[i], pts[j]
        lines.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{ax + wrapd(ax, bx, T):.1f}" y2="{ay + wrapd(ay, by, T):.1f}"/>')
    nodes = []
    for n, h in enumerate(hubs):
        x, y = pts[h]
        d = re.search(r'<path d="([^"]+)"', (ICONS / f"{icons[n]}.svg").read_text()).group(1)
        nodes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="21" class="hub"/>'
                     f'<path d="{d}" class="icon" transform="translate({x - 11:.1f},{y - 11:.1f}) scale(.9167)"/>')
    for i, (x, y) in enumerate(pts):
        if i in hubs:
            continue
        kind = rnd.random()
        if kind < .45:
            nodes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" class="dot"/>')
        elif kind < .8:
            nodes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rnd.choice([5, 7, 9])}" class="ring"/>')
        else:
            nodes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" class="ring"/>'
                         f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="dot"/>')
    style = (f'line{{stroke:{color};stroke-width:1.3}}.hub{{fill:{bg};stroke:{color};stroke-width:2}}'
             f'.icon{{fill:{color}}}.ring{{fill:{bg};stroke:{color};stroke-width:1.5}}.dot{{fill:{color}}}')
    return tile(T, bg, style, "".join(lines), "".join(nodes))


# ---------------------------------------------------------------- CAD: a 3D field of wireframe blocks

def iso_blocks(color, bg, light, seed=9):
    """Blocks of different sizes and heights standing in clusters on an isometric floor, with open
    floor between the clusters. 2:1 pixel isometric, so the floor's lattice repeats on whole pixels
    (one cell is 4u wide and 2u tall)."""
    rnd = random.Random(seed)
    T, u = 720, 18
    D, S = T // (4 * u) * 2, T // u  # cells repeat every D steps of i-j and S steps of i+j
    P = lambda i, j: (2 * u * (i - j), u * (i + j))
    cell = lambda i, j: ((i - j) % D, (i + j) % S)
    bright = mix(color, "#ffffff" if not light else "#000000", .15)
    floor = []
    cells = [(d, s) for d in range(D) for s in range(S) if (d + s) % 2 == 0]
    for d, s in cells:
        i, j = (s + d) // 2, (s - d) // 2
        (x0, y0), (x1, y1), (x3, y3) = P(i, j), P(i + 1, j), P(i, j + 1)
        floor.append(f'<path d="M{x3},{y3} L{x0},{y0} L{x1},{y1}" class="floor"/>')
    # Blocks gather around a few centres; the floor between them stays open.
    centres = [(rnd.uniform(0, T), rnd.uniform(0, T)) for _ in range(3)]
    def near(i, j):
        x, y = P(i + .5, j + .5)
        return max(math.exp(-(wrapd(x, cx, T) ** 2 + wrapd(y, cy, T) ** 2) / (2 * 120 ** 2)) for cx, cy in centres)
    used, items = set(), []
    order = cells[:]
    rnd.shuffle(order)
    for d, s in order:
        i, j = (s + d) // 2, (s - d) // 2
        r = rnd.random()
        if r < .45 * near(i, j):
            n = 2 if rnd.random() < .4 else 1  # footprint: 1×1 or 2×2 cells
            foot = {cell(i + a, j + b) for a in range(-1, n + 1) for b in range(-1, n + 1)}  # with a gap around
            if foot & used:
                continue
            used |= foot
            items.append(("block", i, j, n, rnd.choice([1, 2, 2, 3, 4]) * u * (.9 if n == 1 else 1.1)))
        elif r > .985:
            items.append(("pillar", i, j, 1, rnd.uniform(1.5, 5) * u))
    drawn = []
    for kind, i, j, n, h in items:
        for oi, oj in [(a + b, b - a) for a in (-D // 2, 0, D // 2) for b in (-S // 2, 0, S // 2)]:
            ii, jj = i + oi, j + oj  # the same item one tile left/right (a) and up/down (b)
            x2, y2 = P(ii + n, jj + n)
            if not (-160 < x2 < T + 160 and -20 < y2 < T + 220):
                continue
            drawn.append((y2, kind, ii, jj, n, h))
    out = []
    for _, kind, i, j, n, h in sorted(drawn):  # back to front, so nearer blocks hide what's behind
        if kind == "pillar":
            x, y = P(i + 1, j + 1)
            out.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y - h:.1f}" class="pillar"/>'
                       f'<circle cx="{x}" cy="{y - h:.1f}" r="1.8" class="node"/>')
            continue
        p0, p1, p2, p3 = P(i, j), P(i + n, j), P(i + n, j + n), P(i, j + n)
        q = [(x, y - h) for x, y in (p0, p1, p2, p3)]
        pts = lambda *ps: " ".join(f"{x:.1f},{y:.1f}" for x, y in ps)
        out.append(f'<polygon points="{pts(q[3], q[2], p2, p3)}" class="side"/>'
                   f'<polygon points="{pts(q[1], q[2], p2, p1)}" class="side"/>'
                   f'<polygon points="{pts(*q)}" class="top"/>')
        out.extend(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" class="node"/>' for x, y in q)
    style = (f'.floor{{fill:none;stroke:{color};stroke-width:1;opacity:.35}}'
             f'.side{{fill:{bg};stroke:{color};stroke-width:1.2;stroke-linejoin:round}}'
             f'.top{{fill:{mix(bg, color, .15)};stroke:{color};stroke-width:1.2;stroke-linejoin:round}}'
             f'.pillar{{stroke:{color};stroke-width:1;opacity:.6}}.node{{fill:{bright}}}')
    return tile(T, bg, style, "".join(floor), extra="".join(out))


DRAW = {"pin-grid": pin_grid, "hex-dump": hex_dump, "icon-graph": icon_graph, "iso-blocks": iso_blocks}


def render(out, light=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, (_kind, dark, lite) in PATTERNS.items():
        svg = DRAW[name](lite if light else dark, LIGHT_BG if light else DARK_BG, light)
        stem = f"{name}-light" if light else name
        (out / f"{stem}.svg").write_text(svg)
        subprocess.run(["rsvg-convert", "-o", str(out / f"{stem}.png"), str(out / f"{stem}.svg")], check=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    render(args[0] if args else "patterns/out", light="--light" in sys.argv)
