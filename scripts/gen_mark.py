#!/usr/bin/env python3
"""Generate the woven AS monogram as static SVG assets.

The mark is one dense fabric; the A and S are the region where the green
threads surface, woven through the same warp/weft as the white ground.
Single source of truth so the asset can be regenerated/retrademarked later.
"""
import os

A = [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"]
S = [".####", "#....", "#....", ".###.", "....#", "....#", "####."]
COMB = [A[r] + "." + S[r] for r in range(7)]   # 11 wide x 7 tall
BCOLS, BROWS = 11, 7
CU, PAD = 6, 18


def is_letter(i, j, scale):
    bc, br = i // scale, j // scale
    if not (0 <= br < BROWS and 0 <= bc < BCOLS):
        return False
    return COMB[br][bc] == "#"


def cell(i, j, scale, gx, gy, green, weave, light):
    isL = is_letter(i, j, scale)
    cx, cy = gx + i * CU + CU / 2, gy + j * CU + CU / 2
    warp_over = ((((i - j) % 4) + 4) % 4 < 2) if weave == "twill" else ((i + j) % 2 == 0)
    segW, pillW, ext, pext = CU * 0.30, CU * 0.64, CU * 1.04, CU * 1.22
    segCol = "#168f4d" if isL else ("#dcd7c9" if light else "#222f3e")
    pillCol = green if isL else ("#efebe1" if light else "#2f3d4f")
    out = []
    out.append(f'<rect x="{cx-segW/2:.1f}" y="{cy-ext/2:.1f}" width="{segW:.1f}" height="{ext:.1f}" rx="{segW/2:.1f}" fill="{segCol}"/>')
    out.append(f'<rect x="{cx-ext/2:.1f}" y="{cy-segW/2:.1f}" width="{ext:.1f}" height="{segW:.1f}" rx="{segW/2:.1f}" fill="{segCol}"/>')
    if warp_over:
        out.append(f'<rect x="{cx-pillW/2:.1f}" y="{cy-pext/2:.1f}" width="{pillW:.1f}" height="{pext:.1f}" rx="{pillW/2:.1f}" fill="{pillCol}"/>')
    else:
        out.append(f'<rect x="{cx-pext/2:.1f}" y="{cy-pillW/2:.1f}" width="{pext:.1f}" height="{pillW:.1f}" rx="{pillW/2:.1f}" fill="{pillCol}"/>')
    return "".join(out)


def build(scale=3, green="#23d96a", weave="twill", light=True, tile=True, under=True):
    wcols, wrows = BCOLS * scale, BROWS * scale
    gridW, gridH = wcols * CU, wrows * CU
    side = gridW + PAD * 2
    gx, gy = PAD, (side - gridH) / 2
    r = side * 0.18 if tile else 0
    ground = "#f1efe8" if light else "#0d141d"
    cells = "".join(cell(i, j, scale, gx, gy, green, weave, light)
                    for j in range(wrows) for i in range(wcols))
    under_layer = f'<rect x="0" y="0" width="{side}" height="{side}" fill="{green}" opacity="0.10"/>' if under else ""
    bg = f'<rect x="0" y="0" width="{side}" height="{side}" fill="{ground}"/>' if tile else ""
    border = f'<rect x="0.5" y="0.5" width="{side-1}" height="{side-1}" rx="{r:.1f}" fill="none" stroke="#00000018"/>' if tile else ""
    clip = f'<clipPath id="clip"><rect x="0" y="0" width="{side}" height="{side}" rx="{r:.1f}"/></clipPath>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" role="img" aria-label="AS monogram">
  <title>AS — Anand Suresh</title>
  <defs>{clip}</defs>
  <g clip-path="url(#clip)">{bg}{under_layer}{cells}</g>
  {border}
</svg>'''


OUT = os.path.join(os.path.dirname(__file__), "brand")
os.makedirs(OUT, exist_ok=True)
assets = {
    "as-logo.svg":         dict(scale=3, light=True,  tile=True),   # hero / nav, white tile
    "as-logo-dark.svg":    dict(scale=3, light=False, tile=True),   # dark-chrome tile
    "as-favicon.svg":      dict(scale=2, light=True,  tile=True),   # thicker threads for tiny sizes
    "as-mark.svg":         dict(scale=3, light=True,  tile=False, under=False),  # transparent, no tile
}
for name, kw in assets.items():
    with open(os.path.join(OUT, name), "w") as f:
        f.write(build(**kw))
    print("wrote", name, os.path.getsize(os.path.join(OUT, name)), "bytes")
