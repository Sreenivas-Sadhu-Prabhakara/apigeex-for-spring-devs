# Apigee X for Spring Boot Developers

A from-the-basics **Apigee X** learning site aimed at experienced **Java / Spring Boot microservices developers**. Every Apigee concept is bridged to a Spring concept you already know, taught against a **UK Open Banking / FAPI** running domain, with copy-pasteable code, hands-on labs in a free Apigee X eval org, and an **Apolaki** (sun/war) dark theme.

> **Status:** Planning. The implementation plan lives in [`PLAN.md`](./PLAN.md). Content and the static site (built from `content/` → `docs/` via `build.py`) will land here once the plan is approved.

## Planned structure

```
content/        Markdown sessions + curriculum.json (single source of truth)
assets/         Apolaki design system, SVG diagrams, hero images
build.py        Renders content/ → static HTML in docs/
docs/           Pre-rendered site served by GitHub Pages
```

## Course shape

32 atomic, cumulative sessions across 7 parts: Foundations & the Apigee mental model → Flow & mediation engine → Security, identity & API products → FAPI 1.0 Advanced & the OB trust framework → Building the UK Open Banking APIs → Operations, delivery & observability → Capstone. Each session is self-contained with one objective, an explicit "builds on" link, a Spring Boot bridge, a hands-on lab, and a stretch goal.
