# Hero image prompts — "Apolaki" edition

These are ready-to-run prompts for generating the **8 hero images** (1 splash + 7 part
openers). Until you generate them, the site renders the abstract SVG placeholders in
this folder (`tools/gen_placeholders.py`).

## Rules (read first)

- **Abstract / mood only — never a technical diagram.** Heroes orient and set tone;
  they must not encode API concepts, arrows, boxes, or labels. The teaching is done by
  the hand-authored SVGs in `assets/svg/`.
- **No text in the image.** Titles are overlaid as crisp HTML from `manifest.json`.
- **Palette — Apolaki:** charcoal night `#0F1115`, solar gold `#F5A524`, ember
  `#FF6B1A`, war-red `#E03131` (sparingly), warm off-white highlights `#FFE6B0`.
- **Motif:** the sun/war deity Apolaki — a solar disc, rays, dawn light over a dark
  horizon. Keep the left ~40% darker/quieter so the overlaid headline stays legible.
- **Aspect:** splash ≈ 1200×400; part openers ≈ 1200×300. Export as PNG (or WebP),
  drop into this folder, and point the matching `src` in `manifest.json` at it.

## Shared style suffix (append to every prompt)

> Dark charcoal background (#0F1115), solar gold and ember palette, minimal abstract
> composition, soft volumetric light, subtle film grain, no text, no lettering, no
> diagrams, no UI, cinematic, high contrast, left side darker for text overlay.
> Wide banner aspect ratio.

---

## splash.svg → `splash` (1200×400)

> An immense stylised sun cresting a dark horizon, concentric solar rings and fine
> radiating rays, embers drifting upward, a sense of dawn breaking over a calm dark
> plain. Calm, confident, the beginning of a journey.

## part-1.svg → Part 1 · Foundations

> A single clean solar disc low on the right at first light, faint geometric ground
> grid dissolving into darkness — the foundation being laid.

## part-2.svg → Part 2 · Flow & mediation

> Streams of warm light bending and flowing symmetrically around a sun on the left,
> like currents threading through a channel — motion and mediation.

## part-3.svg → Part 3 · Security & identity

> A sun half-eclipsed behind overlapping translucent shield-like planes, gold light
> rimming hardened edges — protection without literal locks.

## part-4.svg → Part 4 · FAPI & the OB trust framework

> Interlocking concentric rings orbiting a sun on the left, precise and engineered,
> conveying a strict framework of trust.

## part-5.svg → Part 5 · Building the OB APIs

> A constellation of warm nodes connected by faint light threads beneath a rising sun,
> a network coming alive — building something real.

## part-6.svg → Part 6 · Operations & observability

> A steady high sun over a long level horizon with faint gauge-like arcs of light,
> calm and operational, everything running smoothly.

## part-7.svg → Part 7 · Capstone

> A full sun at zenith in clearing sky, brightest and most complete of the set, rays
> reaching the frame edges — culmination and readiness.
