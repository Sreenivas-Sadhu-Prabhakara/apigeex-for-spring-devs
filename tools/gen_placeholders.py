#!/usr/bin/env python3
"""tools/gen_placeholders.py — emit abstract Apolaki "sun" hero placeholders.

These are deliberately text-free, mood-only orientation art (per the engineer-
audience rule: hero images never carry technical information). The real PNGs are
generated later from assets/heroes/PROMPTS.md and dropped in beside these; until
then the site renders these SVGs. Re-run any time:

    python3 tools/gen_placeholders.py

Output: assets/heroes/splash.svg and part-1.svg … part-7.svg
"""

from pathlib import Path

HEROES = Path(__file__).resolve().parent.parent / "assets" / "heroes"

# (filename, width, height, sun centre x%, sun radius, ray count, dawn?)
SLOTS = [
    ("splash", 1200, 400, 0.72, 230, 28, True),
    ("part-1", 1200, 300, 0.80, 150, 20, True),
    ("part-2", 1200, 300, 0.24, 140, 22, False),
    ("part-3", 1200, 300, 0.82, 160, 24, False),
    ("part-4", 1200, 300, 0.30, 130, 18, False),
    ("part-5", 1200, 300, 0.78, 150, 22, True),
    ("part-6", 1200, 300, 0.26, 140, 20, False),
    ("part-7", 1200, 300, 0.50, 180, 30, True),
]


def rays(cx, cy, count, r0, r1):
    out = []
    for i in range(count):
        # deterministic, no randomness (keeps regen reproducible)
        ang = (360 / count) * i
        out.append(
            f'<line x1="{cx}" y1="{cy}" x2="{cx}" y2="{cy}" '
            f'transform="rotate({ang} {cx} {cy})" '
            f'x2="{cx}" y2="{cy - r1}" stroke="url(#ray)" stroke-width="2" '
            f'opacity="{0.10 + 0.16 * (i % 3 == 0)}"/>'
        )
    # rebuild cleanly: emit radial ticks
    out = []
    for i in range(count):
        ang = (360 / count) * i
        y2 = cy - r1
        op = 0.30 if i % 3 == 0 else 0.13
        out.append(
            f'<line x1="{cx}" y1="{cy - r0}" x2="{cx}" y2="{y2}" '
            f'transform="rotate({ang} {cx} {cy})" stroke="url(#ray)" '
            f'stroke-width="{2.4 if i % 3 == 0 else 1.4}" opacity="{op}"/>'
        )
    return "\n  ".join(out)


def make(name, w, h, cxf, r, ray_count, dawn):
    cx = int(w * cxf)
    cy = int(h * (0.42 if dawn else 0.5))
    glow = "#FF8A3D" if dawn else "#F5A524"
    sky_top = "#0F1115"
    sky_bot = "#1A120C" if dawn else "#12141A"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Abstract Apolaki sun motif">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{sky_top}"/>
      <stop offset="100%" stop-color="{sky_bot}"/>
    </linearGradient>
    <radialGradient id="sun" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFE6B0"/>
      <stop offset="40%" stop-color="#FFD27A"/>
      <stop offset="72%" stop-color="{glow}"/>
      <stop offset="100%" stop-color="#C9461A" stop-opacity="0.18"/>
    </radialGradient>
    <radialGradient id="halo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{glow}" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="{glow}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="ray" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%" stop-color="#F5A524" stop-opacity="0"/>
      <stop offset="100%" stop-color="#FFD27A"/>
    </linearGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#sky)"/>
  <circle cx="{cx}" cy="{cy}" r="{int(r * 2.0)}" fill="url(#halo)"/>
  <g>
  {rays(cx, cy, ray_count, int(r * 1.08), int(r * 1.9))}
  </g>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#sun)"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#FFD27A" stroke-width="1.5" opacity="0.5"/>
  <circle cx="{cx}" cy="{cy}" r="{int(r * 0.66)}" fill="none" stroke="#FFE6B0" stroke-width="1" opacity="0.25"/>
  <!-- horizon haze -->
  <rect x="0" y="{int(h * 0.74)}" width="{w}" height="{int(h * 0.26)}" fill="#0B0C10" opacity="0.55"/>
</svg>
"""
    (HEROES / f"{name}.svg").write_text(svg, encoding="utf-8")


def main():
    HEROES.mkdir(parents=True, exist_ok=True)
    for slot in SLOTS:
        make(*slot)
    print(f"Wrote {len(SLOTS)} hero placeholders into {HEROES}")


if __name__ == "__main__":
    main()
