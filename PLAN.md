# Plan — "Apigee X for Spring Boot Developers" learning site

## Context

You want a **from-the-basics Apigee X learning website**, aimed specifically at an experienced **Java / Spring Boot microservices developer** who is new to Apigee. It must teach every Apigee concept by bridging to something the learner already knows in Spring, use **UK Open Banking / FAPI** as the running domain, ship **copy-pasteable code** everywhere, use **realistic, well-defined visuals**, and carry an **Apolaki** (Filipino sun/war god) dark theme. It will be a **new public GitHub repo** (`apigeex-for-spring-devs`) served via GitHub Pages from `/docs`.

This is a sibling to your existing `apigeex-training` repo but a distinct deliverable: different audience (Spring devs), different lens (Spring-bridge pedagogy), different theme (Apolaki), richer visuals. It reuses the *proven build pipeline* from that repo (Markdown + `curriculum.json` → flat static HTML via `build.py`), evolved — not reinvented. Honors your house style: **MINTO** (bottom-line first), **MECE** (no topic twice), **atomic-but-cumulative** sessions, plain static hosting with copy buttons.

## Outcome

A polished, dark-Apolaki-themed static site of **32 atomic sessions across 7 parts**, each self-contained with one objective, an explicit "builds on" link, a Spring Boot bridge, a hands-on lab in a free Apigee X eval org, and a stretch goal — generated from a single `curriculum.json` source of truth, live on GitHub Pages.

---

## 1. Repo & deployment

- New local project at `/Users/sreeni/apigeex-for-spring-devs/`, `git init`, push to **public** `Sreenivas-Sadhu-Prabhakara/apigeex-for-spring-devs` via `gh` (already authed, `repo` scope present).
- GitHub Pages: serve `main` → `/docs` (matches your existing setup). `.nojekyll` so files are served verbatim.
- No CI build required — `docs/` is committed pre-rendered. Regenerate with `python3 build.py`.

## 2. Build pipeline (evolve the proven `build.py`)

Port and extend the reference pipeline (`markdown` 3.10 + `pygments` 2.20, both already installed):

- **Source of truth:** `content/curriculum.json` restructured to **parts → sessions** (each session: `id`, global index `01..32`, `part`, `code` like `2.1`, `title`, `objective`, `builds_on`, `bridge`, `stretch`, `minutes`). Sidebar nav, prev/next, progress bar all generate from it — TOC can't drift.
- **Content:** `content/session-NN.md` (01–32) + `index.md`. Markdown so code never needs hand-escaped XML.
- **Keep** from reference: ` ```mermaid ` fences, ` ```widget ` interactive fences, per-page "On this page" TOC, `localStorage` progress + "mark complete", flat `docs/` output.
- **Add:**
  - **Copy buttons on every code block** (extend `app.js`) — fulfills "all code must have copyable code".
  - **Apolaki Pygments theme**: custom `apolaki_pygments.py` Style class (charcoal `#14161B` bg, solar-gold keywords, ember strings, war-red errors) instead of monokai → `docs/assets/pygments.css`.
  - **Mermaid re-themed** to Apolaki dark variables.
  - New content components rendered from Markdown admonitions / attr_list: **Bottom line**, **Spring Boot bridge** (+ "Where the analogy breaks"), **Lab**, **Verify**, **Failure modes**, **Stretch goal** callout boxes.
  - **Hero image slots** per part opener, driven by `assets/heroes/manifest.json` (falls back to placeholder SVG if no raster present).

## 3. Apolaki design system (`assets/style.css`)

Dark theme, confirmed palette: bg `#0F1115`, surface `#1A1D24`, primary solar-gold `#F5A524`, accent ember `#FF6B1A`, accent-2 war-red `#E03131`, text `#ECEDEE`, code bg `#14161B`. Sun-disc / ray motifs in header, part dividers, and hero frames. High code readability; responsive; sticky sidebar + reading-progress bar (ported & re-themed).

## 4. Visual assets

- **Hand-authored SVG (the teaching workhorses, 1 per session)** — themed to Apolaki. Invest in **3 canonical reusable SVGs**, re-highlighted across sessions to reinforce the cumulative thread:
  1. **4-segment flow pipeline** (ProxyEndpoint req → Target req → Target resp → Proxy resp) — the single most valuable asset; recurs as a "you are here" mini-map.
  2. **Entitlement chain** Developer → App → API Product → Proxy → Token.
  3. **OB ecosystem map** (ASPSP/AISP/PISP/CBPII/Directory).
  Plus per-session sequence diagrams (client-creds, auth-code+PKCE, FAPI PAR + mTLS-bound token, AIS consent journey, PIS + idempotency), mTLS north/south, env-group hostname routing, CI/CD promotion.
- **AI hero images (exactly 7, one per part opener + 1 splash)** — abstract/mood, never a fake diagram. I ship **sized placeholder SVGs + `assets/heroes/PROMPTS.md`** with ready-to-run image-gen prompts; you generate PNGs, drop them in `assets/heroes/`, update `manifest.json`. Engineer-audience rule: AI images never carry technical info — only orientation.

## 5. Content architecture — 32 sessions / 7 parts (MECE backbone)

Per-session template (sections, all from one Markdown file):
`Bottom line` → `Builds on` → `Why this exists` → `Spring Boot bridge` (+ "Where the analogy breaks") → `The concept` (one SVG) → `Hands-on lab` (copyable XML/CLI/JS, real eval-org deploy, "what success looks like") → `Verify it` (curl/Trace) → `Common failure modes` → `Stretch goal` → `Recap & next`.

**Part 1 — Foundations & the Apigee mental model (5):** 1.1 What an API-gateway *product* is (≈ Spring Cloud Gateway, but configured not coded) · 1.2 Architecture + free eval org (org/env/env-group/instance) · 1.3 First passthrough reverse proxy · 1.4 Revisions, deploy & rollback (≈ immutable image tags) · 1.5 The Trace/Debug tool = your gateway debugger.

**Part 2 — Flow & mediation engine (7):** 2.1 **Flow model & request/response symmetry** (4 attach points — the keystone; corrects "it's just a filter chain") · 2.2 Message & flow-variable model · 2.3 Conditions, RouteRules, conditional flows · 2.4 AssignMessage & ExtractVariables · 2.5 JavaScript vs Java callouts (the trade-off) · 2.6 Quotas & SpikeArrest (distributed, product-scoped) · 2.7 Caching vs KVM vs PropertySets (the three stores; "KVM is not a database").

**Part 3 — Security, identity & API products (7):** 3.1 Threat protection, CORS, data masking · 3.2 **API Products / Apps / Developers / keys** (entitlement chain — no clean Spring equiv; promoted before OAuth) · 3.3 OAuthV2 as token server (client-creds) · 3.4 Auth-code + PKCE + JWT verify · 3.5 TLS/mTLS, keystores, north/south-bound · 3.6 TargetServers, LB & health · 3.7 Shared flows, FlowHooks & the fault/error taxonomy.

**Part 4 — FAPI 1.0 Advanced & OB trust framework (4):** 4.1 OB trust framework & OBIE roles · 4.2 FAPI Advanced profile: what it requires (PAR, request objects, mTLS-bound tokens, JARM) · 4.3 Implementing FAPI I: PAR + request objects + client auth · 4.4 Implementing FAPI II: mTLS-bound tokens & introspection.

**Part 5 — Building the UK OB APIs (5):** 5.1 Dynamic Client Registration (DCR) · 5.2 Account-access consent lifecycle · 5.3 AISP reads (accounts/balances/transactions) · 5.4 PISP payments + idempotency · 5.5 Confirmation of funds + end-to-end journey.

**Part 6 — Operations, delivery & observability (4):** 6.1 Environments, env groups, hostnames · 6.2 CI/CD config-as-code (apigeecli/Maven) · 6.3 Observability, analytics, custom reports, Advanced API Security (awareness) · 6.4 Product packaging, monetization & API hub (awareness).

**Part 7 — Capstone (1):** 7.1 Assemble a production-grade OB platform + go-live readiness review (+ stretch: run OB conformance suite).

Each session ships a one-line **Spring Boot bridge** and **stretch goal** (already drafted in design). `builds_on` threads the spine: passthrough (1.3) → flow model (2.1) → entitlement (3.2) → FAPI (4.x) → real OB APIs (5.x) → operated platform (6.x) → capstone.

## 6. Labs

Shared `content/session-01`…lab bootstrap covers provisioning a **free Apigee X eval org**, `gcloud`/`apigeecli` install, and a mock target. Every later lab is do-it-yourself with real deploys, copyable commands, and an explicit "what success looks like" (curl output / Trace).

---

## Execution phases (with an early checkpoint)

- **Phase A — Scaffold + design proof.** Project skeleton, evolved `build.py`, Apolaki `style.css` + Pygments theme + copy buttons, `curriculum.json` (all 32 sessions' metadata), the 3 canonical SVGs, hero placeholders/prompts, `index.md`, and **3 fully-authored sample sessions** (1.1, 2.1, 3.2 — one per major lens). Build locally. **Pause and show you the rendered site to sign off on look & feel + session shape before mass authoring.**
- **Phase B — Author the remaining 29 sessions** (Markdown + per-session SVGs), keeping the cumulative thread and MECE discipline.
- **Phase C — Polish:** all SVGs themed, copy buttons verified, nav/progress/TOC checked, `README.md`, `requirements.txt`, `.gitignore`, full local build, link/anchor check.
- **Phase D — Ship:** `git init`, create public repo, push, enable Pages (`main`/`docs`), verify the live URL renders.
- **Phase E — Memory:** add an `apigeex-for-spring-devs-project` memory + index line; cross-link `[[apigeex-training-project]]`, `[[structured-deliverable-style]]`.

## Critical files to create

- `content/curriculum.json` — 7-part / 32-session source of truth.
- `content/index.md`, `content/session-01.md` … `session-32.md`.
- `build.py` — evolved renderer (copy buttons, Apolaki Pygments, hero slots, new callout components).
- `apolaki_pygments.py` — custom Pygments Style.
- `assets/style.css`, `assets/app.js`, `assets/widgets.js`, `assets/widgets.css` (ported + re-themed).
- `assets/svg/flow-pipeline.svg`, `entitlement-chain.svg`, `ob-ecosystem.svg` + per-session SVGs.
- `assets/heroes/PROMPTS.md`, `manifest.json`, placeholder SVGs.
- `README.md`, `requirements.txt`, `.gitignore`.

## Verification

1. `python3 build.py` renders `index.html` + 32 session pages into `docs/` with no errors (JSON in widget/curriculum validated at build time).
2. Open `docs/index.html` locally: Apolaki theme renders, sidebar nav + part grouping correct, prev/next chain 01→32 intact, "On this page" TOC, progress + mark-complete work, **every code block has a working copy button**, SVGs and hero placeholders display sharp.
3. Spot-check 3 sample sessions for template completeness (all 10 sections, bridge + stretch present) and that copied code is valid (XML well-formed, CLI runnable).
4. After push: GitHub Pages URL (`https://sreenivas-sadhu-prabhakara.github.io/apigeex-for-spring-devs/`) loads and renders identically.

**Open the gate at Phase A** — you review the live look & feel and one session of each type before I author the full 29.
