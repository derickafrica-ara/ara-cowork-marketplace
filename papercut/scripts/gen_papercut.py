"""Generate the Papercut backdrop: a cut-paper collage on a clay-orange ground.

Ivory paper shapes with hand-cut edges, layered darker-orange paper, a paper-grain
speckle, two hand-drawn ink threads that draw themselves in once, and an ink bloom
that turns very slowly. Light and dark live in one SVG (prefers-color-scheme).

Usage: python3 gen_papercut.py <hooks dir> <preview dir>
Writes <hooks dir>/scene.js and <preview dir>/preview-{light,dark}.svg.
"""
import json
import math
import random
import sys

W, H = 1600, 1000
rng = random.Random(1977)


def f(n):
    return f"{n:.1f}".rstrip("0").rstrip(".")


def cut(points, seed, step=34, wobble=2.2):
    """A hand-cut polygon: each edge split into short facets, each nudged a little."""
    r = random.Random(seed)
    out = []
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        length = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(length / step))
        nx, ny = -(y2 - y1) / length, (x2 - x1) / length
        for k in range(n):
            t = k / n
            j = 0 if k == 0 else r.uniform(-wobble, wobble)
            out.append((x1 + (x2 - x1) * t + nx * j, y1 + (y2 - y1) * t + ny * j))
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in out) + "Z"


def cut_circle(cx, cy, rad, seed, facets=56, wobble=2.6):
    r = random.Random(seed)
    pts = []
    for i in range(facets):
        a = 2 * math.pi * i / facets
        rr = rad + r.uniform(-wobble, wobble)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


def rotated_square(cx, cy, half, deg):
    a = math.radians(deg)
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    return [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in corners]


def triangle(cx, cy, size, deg=0):
    a0 = math.radians(deg - 90)
    return [(cx + size * math.cos(a0 + k * 2 * math.pi / 3), cy + size * math.sin(a0 + k * 2 * math.pi / 3)) for k in range(3)]


def bloom(cx, cy, petals=11, r0=16, seed=5):
    """An ink doodle bloom: open, slightly uneven petal loops around a small ring."""
    r = random.Random(seed)
    paths = []
    for i in range(petals):
        th = 2 * math.pi * i / petals + r.uniform(-0.07, 0.07)
        r1 = r.uniform(96, 128)
        w = r.uniform(13, 19)
        dx, dy = math.cos(th), math.sin(th)
        nx, ny = -dy, dx
        bx, by = cx + dx * r0, cy + dy * r0
        tx, ty = cx + dx * r1, cy + dy * r1
        mid = r1 * 0.5
        p = (
            f"M{f(bx + nx * 3)} {f(by + ny * 3)}"
            f"C{f(cx + dx * mid + nx * w)} {f(cy + dy * mid + ny * w)} "
            f"{f(tx - dx * 10 + nx * w * 0.45)} {f(ty - dy * 10 + ny * w * 0.45)} {f(tx)} {f(ty)}"
            f"C{f(tx - dx * 10 - nx * w * 0.45)} {f(ty - dy * 10 - ny * w * 0.45)} "
            f"{f(cx + dx * mid - nx * w)} {f(cy + dy * mid - ny * w)} {f(bx - nx * 3)} {f(by - ny * 3)}"
        )
        paths.append(p)
    ring = f"M{f(cx + 11)} {f(cy)}A11 11 0 1 0 {f(cx - 11)} {f(cy)}A11 11 0 1 0 {f(cx + 11)} {f(cy)}"
    return "".join(paths) + ring


# --- paper-grain tile: tiny light and dark specks
grain_light = []
grain_dark = []
for _ in range(12):
    grain_light.append((rng.uniform(0, 48), rng.uniform(0, 48), rng.uniform(0.5, 1.1)))
for _ in range(9):
    grain_dark.append((rng.uniform(0, 48), rng.uniform(0, 48), rng.uniform(0.5, 1.0)))

# --- the composition
BIG_C = (1365, 165)
shapes = {
    # deeper-orange paper, behind everything
    "deep_arc": cut_circle(1610, 1010, 340, 11, facets=70),
    "deep_sq": cut(rotated_square(120, 80, 200, 12), 12),
    # ivory paper
    "big_circle": cut_circle(*BIG_C, 195, 21),
    "square": cut(rotated_square(95, 70, 140, -7), 22),
    "diamond": cut(rotated_square(95, 470, 96, 45), 23),
    "tri": cut([(40, 1012), (252, 688), (472, 1012)], 24),
}
confetti = [
    ("c1", cut_circle(1500, 660, 30, 31, facets=22, wobble=1.2), "f1"),
    ("c2", cut(triangle(1232, 872, 40, 12), 32, step=18, wobble=1.0), "f2"),
    ("c3", cut(rotated_square(305, 335, 20, 18), 33, step=14, wobble=0.8), "f3"),
    ("c4", cut(rotated_square(1556, 430, 18, 45), 34, step=12, wobble=0.8), "f1"),
    ("c5", cut_circle(1120, 70, 14, 35, facets=16, wobble=0.8), "f2"),
]
ink_right = (
    "M1290 372C1230 430 1310 480 1370 505C1430 530 1420 590 1455 620"
    "C1490 650 1560 640 1555 690C1550 740 1470 720 1460 770"
    "C1445 840 1520 880 1470 940C1440 975 1400 990 1380 1012"
)
ink_left = (
    "M236 205C300 250 210 300 262 345C310 390 230 420 228 470"
    "C226 520 300 540 280 600C262 650 200 640 215 690"
)
ink_ring = cut_circle(182, 770, 15, 41, facets=18, wobble=1.4)
bloom_d = bloom(*BIG_C)

LIGHT = {
    "ground": "#cc785c", "deep": "#b5603f", "paper": "#f1ece4", "shade": "#7a3b26",
    "ink": "#1c1210", "gl": "#fbe9dc", "gd": "#5a2a1a",
}
DARK = {
    "ground": "#8a4630", "deep": "#6e3523", "paper": "#dccbbb", "shade": "#2a120a",
    "ink": "#160d0a", "gl": "#e9b9a3", "gd": "#2a120a",
}


def rules(p):
    return (
        f".ground{{fill:{p['ground']}}}.deep{{fill:{p['deep']}}}.paper{{fill:{p['paper']}}}"
        f".shade{{fill:{p['shade']}}}.ink{{stroke:{p['ink']}}}.inkf{{fill:{p['ink']}}}"
        f".gl{{fill:{p['gl']}}}.gd{{fill:{p['gd']}}}"
    )


def css(force=None):
    base = (
        ".shade{opacity:.22}.gl{opacity:.32}.gd{opacity:.16}"
        ".ink{fill:none;stroke-width:4.5;stroke-linecap:round;stroke-linejoin:round}"
        ".thread{stroke-dasharray:1000;stroke-dashoffset:0;animation:draw 8s ease-out .6s both}"
        "@keyframes draw{from{stroke-dashoffset:1000}to{stroke-dashoffset:0}}"
        f".petals{{transform-origin:{BIG_C[0]}px {BIG_C[1]}px;animation:spin 180s linear infinite}}"
        "@keyframes spin{to{transform:rotate(360deg)}}"
        "@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-9px)}}"
        ".f1{animation:bob 15s ease-in-out infinite}"
        ".f2{animation:bob 19s ease-in-out -6s infinite}"
        ".f3{animation:bob 23s ease-in-out -11s infinite}"
        # Phones: fewer, larger moves. The bloom comes in from the corner, the diamond
        # peeks in at the left, the right thread and deep arc keep the lower corner.
        "@media (max-aspect-ratio: 1/1){"
        f".top-right{{transform-origin:{BIG_C[0]}px {BIG_C[1]}px;transform:translate(-400px,60px) scale(.72)}}"
        ".right{transform:translateX(-380px)}"
        ".left{transform:translateX(480px)}"
        ".wide-only{display:none}"
        "}"
    )
    if force == "light":
        return base + rules(LIGHT)
    if force == "dark":
        return base + rules(DARK)
    return base + rules(LIGHT) + "@media (prefers-color-scheme: dark){" + rules(DARK) + "}"


def paper(d, dx=5, dy=7):
    """A paper cut-out with a soft offset shadow under it."""
    return (f'<path class="shade" transform="translate({dx} {dy})" d="{d}"/>'
            f'<path class="paper" d="{d}"/>')


def svg(force=None):
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">',
        f"<style>{css(force)}</style>",
        '<defs><pattern id="grain" width="48" height="48" patternUnits="userSpaceOnUse">'
        + "".join(f'<circle class="gl" cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>' for x, y, r in grain_light)
        + "".join(f'<circle class="gd" cx="{f(x)}" cy="{f(y)}" r="{f(r)}"/>' for x, y, r in grain_dark)
        + "</pattern></defs>",
        f'<rect class="ground" width="{W}" height="{H}"/>',
        f'<rect width="{W}" height="{H}" fill="url(#grain)"/>',
        # left cluster: deep square, ivory square, diamond, triangle and the thread joining them
        '<g class="left">',
        '<g class="wide-only">',
        f'<path class="deep" d="{shapes["deep_sq"]}"/>',
        paper(shapes["square"]),
        "</g>",
        paper(shapes["diamond"]),
        '<g class="wide-only">',
        paper(shapes["tri"]),
        f'<path class="ink thread" pathLength="1000" d="{ink_left}"/>',
        f'<path class="ink" d="{ink_ring}"/>',
        "</g>",
        f'<g class="f3"><path class="shade" transform="translate(3 4)" d="{confetti[2][1]}"/><path class="paper" d="{confetti[2][1]}"/></g>',
        "</g>",
        # right side: deep arc, thread, confetti
        '<g class="right">',
        f'<path class="deep" d="{shapes["deep_arc"]}"/>',
        f'<path class="ink thread" pathLength="1000" d="{ink_right}"/>',
    ]
    for name, d, anim in (confetti[0], confetti[1], confetti[3]):
        p.append(f'<g class="{anim}"><path class="shade" transform="translate(3 4)" d="{d}"/><path class="paper" d="{d}"/></g>')
    # Three short ink motion marks trailing the small floating triangle.
    p.append('<g class="f2"><path class="ink" d="M1150 858h24M1140 874h30M1150 890h24"/></g>')
    p.append("</g>")
    # top right: the ivory circle with the ink bloom, and a small dot
    p.append('<g class="top-right">')
    p.append(paper(shapes["big_circle"], 6, 9))
    p.append(f'<g class="petals"><path class="ink" stroke-width="4" d="{bloom_d}"/></g>')
    p.append("</g>")
    p.append(f'<g class="f2"><path class="paper" d="{confetti[4][1]}"/></g>')
    p.append("</svg>")
    return "".join(p)


scene = svg()
assert len(scene) < 131072, len(scene)
for bad in ["\\", "<!--", "&", "href", "<image", "@import", "@font-face", "CDATA", "<?"]:
    assert bad not in scene, bad

with open(f"{sys.argv[1]}/scene.js", "w") as fh:
    fh.write("// Generated by scripts/gen_papercut.py: a cut-paper collage on a clay-orange ground.\n")
    fh.write(f"export const SCENE = {json.dumps(scene)}\n")
for mode in ("light", "dark"):
    with open(f"{sys.argv[2]}/preview-{mode}.svg", "w") as fh:
        fh.write(svg(mode))
print(len(scene), "chars")
