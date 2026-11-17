"""Generate the Woodgrain backdrop: a chunky pixel-art scene on a 160x100 grid.

Writes hooks/scene.js (the SVG as a string constant) and a preview.svg per mode.
Colors sit in a warm tonal range: ivory and slate neutrals, clay orange,
dusty blue and olive green, banded the way late-1970s consoles drew skies.
"""
import json
import random
import sys

W, H = 160, 100
rng = random.Random(2600)
out_dir = sys.argv[1]
preview_dir = sys.argv[2]

# --- sky bands: (y, height, class) -- discrete stripes, no smooth gradients
sky = [
    (0, 30, "k0"), (30, 8, "k1"), (38, 6, "k2"), (44, 5, "k3"),
    (49, 4, "k4"), (53, 3, "k5"), (56, 3, "k6"), (59, 3, "k7"), (62, 20, "k8"),
]

# --- stars: 1x1 pixels, three twinkle groups
def clear_sky(x, y):
    """Keep stars off the corner tag and the sunburst."""
    # Wide screens, then where the portrait rule moves the tag (+52) and sunburst (-30, +8).
    on_tag = (3 <= x <= 40 or 55 <= x <= 92) and 2 <= y <= 12
    on_moon = (112 <= x <= 136 and 6 <= y <= 27) or (82 <= x <= 106 and 14 <= y <= 35)
    return not (on_tag or on_moon)


def sky_points(count, y_lo, y_hi):
    pts = []
    while len(pts) < count:
        x, y = rng.randrange(0, W), rng.randrange(y_lo, y_hi)
        if clear_sky(x, y):
            pts.append((x, y))
    return pts


stars = {0: [], 1: [], 2: []}
for x, y in sky_points(70, 0, 50):
    stars[rng.randrange(3)].append((x, y))
bright = sky_points(9, 2, 40)


def stepped(base_y, min_h, max_h, step_w, seed, width=W):
    """A stepped mountain silhouette as an H/V-only path, so every edge is a pixel edge."""
    r = random.Random(seed)
    d = [f"M0 {H}"]
    x, h = 0, r.randint(min_h, max_h)
    while x < width:
        d.append(f"V{base_y - h}")
        x2 = min(width, x + step_w * r.randint(1, 3))
        d.append(f"H{x2}")
        x = x2
        h = max(min_h, min(max_h, h + r.choice([-3, -2, -1, 1, 2, 3])))
    d.append(f"V{H}Z")
    return "".join(d)


back_mtn = stepped(66, 4, 16, 3, 7, W + 40)
front_mtn = stepped(74, 2, 9, 2, 11)

# --- a 12-ray pixel sunburst in clay orange, by day and by night.
# X: the steady core and inner rays; T: the ray tips, which glow slowly.
SUNBURST = [
    ".......T.......",
    "...T...T...T...",
    "....T..X..T....",
    ".T...X.X.X...T.",
    "..T...XXX...T..",
    "...XX.XXX.XX...",
    ".....XXXXX.....",
    "TTXXXXXXXXXXXTT",
    ".....XXXXX.....",
    "...XX.XXX.XX...",
    "..T...XXX...T..",
    ".T...X.X.X...T.",
    "....T..X..T....",
    "...T...T...T...",
    ".......T.......",
]


def sprite(rows, x0, y0, mark):
    return "".join(
        f'<rect x="{x0 + x}" y="{y0 + y}" width="1" height="1"/>'
        for y, row in enumerate(rows) for x, c in enumerate(row) if c == mark)


burst_core = sprite(SUNBURST, 117, 9, "X")
burst_tips = sprite(SUNBURST, 117, 9, "T")

# --- clouds (day only): chunky stacked rects
def cloud(x, y):
    return (f'<rect x="{x + 3}" y="{y}" width="7" height="1"/>'
            f'<rect x="{x + 1}" y="{y + 1}" width="12" height="1"/>'
            f'<rect x="{x}" y="{y + 2}" width="16" height="2"/>')

clouds = cloud(18, 14) + cloud(64, 14) + cloud(96, 28) + cloud(140, 18)

# --- the saucer, 10x5 pixels
saucer_rows = [
    "...DDDD...",
    "..DDDDDD..",
    "BBBBBBBBBB",
    ".BLBBLBBL.",
    "..B....B..",
]
saucer = []
for y, row in enumerate(saucer_rows):
    for x, c in enumerate(row):
        if c != ".":
            cls = {"D": "sd", "B": "sb", "L": "sl"}[c]
            saucer.append(f'<rect class="{cls}" x="{x}" y="{y}" width="1" height="1"/>')
saucer_g = "".join(saucer)

# --- 3x5 pixel lettering for the corner tag
FONT = {
    "P": ["XXX", "X.X", "XXX", "X..", "X.."],
    "L": ["X..", "X..", "X..", "X..", "XXX"],
    "A": [".X.", "X.X", "XXX", "X.X", "X.X"],
    "Y": ["X.X", "X.X", ".X.", ".X.", ".X."],
    "E": ["XXX", "X..", "XX.", "X..", "XXX"],
    "R": ["XX.", "X.X", "XX.", "X.X", "X.X"],
    "1": [".X.", "XX.", ".X.", ".X.", "XXX"],
    " ": ["...", "...", "...", "...", "..."],
}


def lettering(text, x0, y0):
    rects = []
    for i, ch in enumerate(text):
        for y, row in enumerate(FONT[ch]):
            for x, c in enumerate(row):
                if c == "X":
                    rects.append(f'<rect x="{x0 + i * 4 + x}" y="{y0 + y}" width="1" height="1"/>')
    return "".join(rects)


tag = lettering("PLAYER 1", 6, 5)

# --- ground stripes and the woodgrain strip at the foot
ground = [(76, 4, "g0"), (80, 3, "g1"), (83, 5, "g2"), (88, 6, "g3")]
wood = ['<rect class="w0" x="0" y="94" width="160" height="6"/>']
for _ in range(26):
    y = rng.randrange(94, 100)
    x = rng.randrange(-10, W)
    wood.append(f'<rect class="w{rng.choice([1, 2])}" x="{x}" y="{y}" width="{rng.randrange(8, 30)}" height="1"/>')

# Palette: light mode is the default rule set, dark overrides it.
LIGHT = {
    "k0": "#c9d7e6", "k1": "#d6dfe6", "k2": "#e3e6e3", "k3": "#ece9df", "k4": "#efe2cf",
    "k5": "#ebdbbc", "k6": "#e3c1a5", "k7": "#d4a27f", "k8": "#e8e6dc",
    "mb": "#b0aea5", "mf": "#788c5d",
    "g0": "#8fa070", "g1": "#788c5d", "g2": "#8fa070", "g3": "#62744b",
    "w0": "#9c7a5b", "w1": "#b8946e", "w2": "#7d6047",
    "spk": "#d97757", "cl": "#faf9f5", "tag": "#c15f3c",
    "sd": "#6a9bcc", "sb": "#3d3d3a", "sl": "#d97757",
}
DARK = {
    "k0": "#141413", "k1": "#1b1b1d", "k2": "#222327", "k3": "#2c2b2c", "k4": "#3d2f2a",
    "k5": "#5c3a2e", "k6": "#8a4f3a", "k7": "#b5603f", "k8": "#141413",
    "mb": "#3d3d3a", "mf": "#4a5638",
    "g0": "#2f3826", "g1": "#262e1f", "g2": "#2f3826", "g3": "#20271a",
    "w0": "#3d2e22", "w1": "#5c4433", "w2": "#2a1f17",
    "spk": "#d97757", "cl": "#faf9f5", "tag": "#d97757",
    "sd": "#6a9bcc", "sb": "#e8e6dc", "sl": "#d97757",
}


def rules(pal):
    return "".join(f".{k}{{fill:{v}}}" for k, v in pal.items())


def css(force=None):
    light = rules(LIGHT) + ".night{opacity:0}.day{opacity:1}"
    dark = rules(DARK) + ".night{opacity:1}.day{opacity:0}.scan{opacity:1}"
    base = (
        "svg{shape-rendering:crispEdges}"
        ".scan{opacity:.55}"
        "@keyframes tw{0%,100%{opacity:1}50%{opacity:.3}}"
        ".t0{animation:tw 7s ease-in-out infinite}"
        ".t1{animation:tw 9s ease-in-out 2s infinite}"
        ".t2{animation:tw 11s ease-in-out 5s infinite}"
        "@keyframes drift{from{transform:translateX(-50px)}to{transform:translateX(170px)}}"
        ".ufo{animation:drift 150s steps(220,end) -50s infinite}"
        "@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-1px)}}"
        ".hover{animation:bob 6s steps(2,end) infinite}"
        "@keyframes slide{from{transform:translateX(0)}to{transform:translateX(-40px)}}"
        ".far{animation:slide 240s steps(40,end) infinite alternate}"
        "@keyframes glow{0%,100%{opacity:1}50%{opacity:.45}}"
        ".tips{animation:glow 6s ease-in-out infinite}"
        "@media (max-aspect-ratio: 1/1){.orbs{transform:translate(-30px,8px)}.tag{transform:translateX(52px)}}"
    )
    if force == "light":
        return base + light
    if force == "dark":
        return base + dark
    return base + light + "@media (prefers-color-scheme: dark){" + dark + "}"


def svg(force=None):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">',
        f"<style>{css(force)}</style>",
        '<defs><pattern id="scanlines" width="4" height="1" patternUnits="userSpaceOnUse">'
        '<rect y="0.66" width="4" height="0.34" fill="#000000" fill-opacity="0.22"/></pattern></defs>',
    ]
    for y, h, c in sky:
        parts.append(f'<rect class="{c}" x="0" y="{y}" width="{W}" height="{h}"/>')
    parts.append('<g class="night">')
    for g, pts in stars.items():
        parts.append(f'<g class="t{g}" fill="#faf9f5">' + "".join(
            f'<rect x="{x}" y="{y}" width="1" height="1"/>' for x, y in pts) + "</g>")
    parts.append('<g fill="#ebdbbc">' + "".join(
        f'<rect x="{x - 1}" y="{y}" width="3" height="1"/><rect x="{x}" y="{y - 1}" width="1" height="3"/>'
        for x, y in bright) + "</g>")
    parts.append("</g>")
    parts.append(f'<g class="day cl">{clouds}</g>')
    parts.append(f'<g class="orbs"><g class="spk">{burst_core}</g><g class="spk tips">{burst_tips}</g></g>')
    parts.append(f'<g class="tag">{tag}</g>')
    parts.append(f'<g class="far"><path class="mb" d="{back_mtn}"/></g>')
    parts.append(f'<path class="mf" d="{front_mtn}"/>')
    for y, h, c in ground:
        parts.append(f'<rect class="{c}" x="0" y="{y}" width="{W}" height="{h}"/>')
    parts.extend(wood)
    parts.append(f'<g transform="translate(30 24)"><g class="ufo"><g class="hover">{saucer_g}</g></g></g>')
    parts.append(f'<rect class="scan" x="0" y="0" width="{W}" height="{H}" fill="url(#scanlines)"/>')
    parts.append("</svg>")
    return "".join(parts)


scene = svg()
assert len(scene) < 131072, len(scene)
for bad in ["\\", "<!--", "&", "href", "<image", "@import", "@font-face", "CDATA"]:
    assert bad not in scene, bad

with open(f"{out_dir}/scene.js", "w") as f:
    f.write("// Generated by scripts/gen_scene.py: a 160x100 pixel-art scene in warm clay, ivory and slate tones.\n")
    f.write(f"export const SCENE = {json.dumps(scene)}\n")

for mode in ("light", "dark"):
    with open(f"{preview_dir}/preview-{mode}.svg", "w") as f:
        f.write(svg(mode))

print(len(scene), "chars")
