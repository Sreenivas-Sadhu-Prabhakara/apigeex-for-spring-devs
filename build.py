#!/usr/bin/env python3
"""
build.py — render content/*.md into plain static HTML under docs/.

Usage:
    pip install -r requirements.txt
    python3 build.py

Design goals:
  * Output is self-contained static HTML — GitHub Pages serves docs/ directly,
    no Jekyll, no MkDocs, no CI build required.
  * Content is authored in Markdown (content/session-NN.md) so code blocks don't
    need hand-escaped XML. Fenced code is highlighted with Pygments using the
    custom Apolaki dark style (apolaki_pygments.py).
  * The left-hand navigation, prev/next links, progress total, and the index map
    are all generated from content/curriculum.json so the table of contents can
    never drift. The curriculum is organised parts -> sessions; each session has a
    global index (01..NN) and a part-local code (e.g. "2.1").

Interactive layer (all client-side, CDN libraries, no build step on hosting):
  * ```mermaid fences          -> rendered diagrams (Mermaid.js, Apolaki-themed)
  * ```widget {json} fences    -> interactive widgets (assets/widgets.js)
  * per-page "On this page" TOC, localStorage progress tracking, copy buttons.

Apolaki content components (authored as Markdown admonitions, styled in CSS):
  !!! bottomline   !!! bridge   !!! breaks   !!! lab   !!! verify
  !!! failure      !!! stretch
"""

import html as _html
import json
import re
import shutil
from pathlib import Path

import seo  # native SEO head-block generator (repo-root seo.py)

import markdown
from pygments.formatters import HtmlFormatter

from apolaki_pygments import ApolakiStyle

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
DOCS = ROOT / "docs"

MD_EXTENSIONS = [
    "fenced_code",
    "codehilite",
    "tables",
    "toc",
    "admonition",
    "attr_list",
    "sane_lists",
    "def_list",
    "md_in_html",
]
MD_CONFIG = {
    "codehilite": {"guess_lang": False, "noclasses": False},
    "toc": {"permalink": False, "toc_depth": "2-3"},
}

_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_WIDGET_RE = re.compile(r"```widget\s*\n(.*?)```", re.DOTALL)


def load_curriculum():
    return json.loads((CONTENT / "curriculum.json").read_text(encoding="utf-8"))


def load_heroes():
    manifest = ASSETS / "heroes" / "manifest.json"
    if manifest.exists():
        return json.loads(manifest.read_text(encoding="utf-8"))
    return {"splash": None, "parts": {}}


def session_order(curriculum):
    """Flat list of global session indices in curriculum order."""
    order = []
    for part in curriculum["parts"]:
        order.extend(part["sessions"])
    return order


def part_openers(curriculum):
    """Map global session index -> part id, for the first session of each part."""
    openers = {}
    for part in curriculum["parts"]:
        if part["sessions"]:
            openers[part["sessions"][0]] = part["id"]
    return openers


# ---------------------------------------------------------------- fence handling
def _extract_fences(text):
    """Pull ```mermaid and ```widget fences out before Markdown runs.

    Returns (text_with_placeholders, replacements) where replacements maps a
    placeholder token to the final HTML to substitute back in afterwards.
    """
    replacements = {}

    def _mermaid(m):
        token = f"MERMAIDBLOCK{len(replacements)}ENDBLOCK"
        diagram = _html.escape(m.group(1).strip())
        replacements[token] = f'<pre class="mermaid">{diagram}</pre>'
        return f"\n\n{token}\n\n"

    def _widget(m):
        token = f"WIDGETBLOCK{len(replacements)}ENDBLOCK"
        raw = m.group(1).strip()
        # Validate JSON at build time so a typo fails the build, not the browser.
        cfg = json.loads(raw)
        wtype = cfg.get("type", "unknown")
        payload = _html.escape(json.dumps(cfg), quote=False)
        replacements[token] = (
            f'<div class="widget" data-widget="{wtype}">'
            f'<script type="application/json">{payload}</script></div>'
        )
        return f"\n\n{token}\n\n"

    text = _MERMAID_RE.sub(_mermaid, text)
    text = _WIDGET_RE.sub(_widget, text)
    return text, replacements


def render_markdown(text):
    """Return (html, toc_html)."""
    text, replacements = _extract_fences(text)
    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_CONFIG)
    out = md.convert(text)
    for token, repl in replacements.items():
        # Markdown wraps a bare token line in <p>…</p>; strip that wrapper.
        out = out.replace(f"<p>{token}</p>", repl).replace(token, repl)
    toc = getattr(md, "toc", "") or ""
    return out, toc


# ------------------------------------------------------------------ page chrome
def sidebar_html(curriculum, active_id):
    """Build the part-grouped navigation shared by every page."""
    sessions = curriculum["sessions"]
    total = len(sessions)
    out = ['<nav class="sidebar" aria-label="Curriculum">']
    out.append(
        '<a class="brand" href="index.html">'
        '<span class="brand-mark" aria-hidden="true"></span>'
        '<span class="brand-text">Apigee&nbsp;X <em>for Spring devs</em></span></a>'
    )
    out.append(
        '<div class="nav-progress"><div class="nav-progress-bar">'
        '<span id="navProgressFill"></span></div>'
        f'<span id="navProgressText" class="nav-progress-text">0 / {total} complete</span></div>'
    )
    for part in curriculum["parts"]:
        out.append(f'<div class="nav-part">{_html.escape(part["title"])}</div>')
        out.append("<ul>")
        for sid in part["sessions"]:
            meta = sessions[str(sid)]
            cls = ' class="active"' if sid == active_id else ""
            label = (
                f'<span class="seqnum">{meta["code"]}</span> '
                f'<span class="seqtitle">{_html.escape(meta["title"])}</span>'
            )
            out.append(
                f'<li{cls} data-session="{sid}"><a href="session-{sid:02d}.html">'
                f'<span class="done-check" aria-hidden="true">&#10003;</span>{label}</a></li>'
            )
        out.append("</ul>")
    out.append("</nav>")
    return "\n".join(out)


def _scripts(total):
    """CDN libraries + local scripts. Mermaid themed to the Apolaki palette.

    A small inline config exposes the dynamic session total + storage key so the
    progress JS never hard-codes a count that could drift from curriculum.json.
    """
    return f"""
  <script>
    window.__COURSE__ = {{ total: {total}, key: "apigeex-spring.progress.v1" }};
  </script>
  <script type="module">
    if (document.querySelector('.mermaid')) {{
    const {{ default: mermaid }} = await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs');
    mermaid.initialize({{
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'base',
      themeVariables: {{
        background: '#1A1D24',
        primaryColor: '#1F2530', primaryBorderColor: '#F5A524', primaryTextColor: '#ECEDEE',
        lineColor: '#7A8290', secondaryColor: '#2A1B12', tertiaryColor: '#241a0f',
        secondaryBorderColor: '#FF6B1A', tertiaryBorderColor: '#E03131',
        noteBkgColor: '#241a0f', noteTextColor: '#ECEDEE', noteBorderColor: '#F5A524',
        fontFamily: '-apple-system, Segoe UI, Roboto, sans-serif', fontSize: '14px'
      }}
    }});
    await mermaid.run({{ querySelector: '.mermaid' }});
    window.__mermaidReady = true;
    }}
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script defer src="assets/widgets.js"></script>
  <script defer src="assets/app.js"></script>
"""


def page_shell(title, sidebar, body, *, total, toc_html="", session=None, is_index=False, seo_head=""):
    main_attrs = f' data-session="{session}"' if session else ""
    main_cls = "content index" if is_index else "content"
    toc_rail = ""
    if toc_html and not is_index:
        toc_rail = (
            '<aside class="toc-rail" aria-label="On this page">'
            '<div class="toc-title">On this page</div>'
            f"{toc_html}</aside>"
        )
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="apolaki">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="assets/pygments.css">
  <link rel="stylesheet" href="assets/style.css">
  <link rel="stylesheet" href="assets/widgets.css">
{seo_head}
</head>
<body>
  <div id="readingBar"></div>
  <button id="navToggle" class="nav-toggle" aria-label="Toggle navigation">&#9776; Menu</button>
  <div class="layout">
    {sidebar}
    <main class="{main_cls}"{main_attrs}>
      {body}
    </main>
    {toc_rail}
  </div>
{_scripts(total)}
</body>
</html>
"""


def hero_html(hero):
    """Render a part-opener / splash hero from a manifest entry, or nothing."""
    if not hero:
        return ""
    src = _html.escape(hero.get("src", ""))
    alt = _html.escape(hero.get("alt", ""))
    eyebrow = hero.get("eyebrow", "")
    headline = hero.get("headline", "")
    cap = (
        f'<figcaption class="hero-cap">'
        f'<span class="hero-eyebrow">{_html.escape(eyebrow)}</span>'
        f'<span class="hero-headline">{_html.escape(headline)}</span></figcaption>'
        if (eyebrow or headline)
        else ""
    )
    return (
        f'<figure class="hero">'
        f'<img src="{src}" alt="{alt}" loading="lazy">'
        f"{cap}</figure>"
    )


def prev_next_html(curriculum, sid):
    sessions = curriculum["sessions"]
    order = session_order(curriculum)
    idx = order.index(sid)
    parts = ['<div class="pager">']
    if idx > 0:
        p = order[idx - 1]
        parts.append(
            f'<a class="prev" href="session-{p:02d}.html">'
            f'<span class="pager-dir">&larr; Previous</span>'
            f'<span class="pager-label">{sessions[str(p)]["code"]} · {_html.escape(sessions[str(p)]["title"])}</span></a>'
        )
    else:
        parts.append(
            '<a class="prev" href="index.html">'
            '<span class="pager-dir">&larr;</span>'
            '<span class="pager-label">Overview</span></a>'
        )
    if idx < len(order) - 1:
        n = order[idx + 1]
        parts.append(
            f'<a class="next" href="session-{n:02d}.html">'
            f'<span class="pager-dir">Next &rarr;</span>'
            f'<span class="pager-label">{sessions[str(n)]["code"]} · {_html.escape(sessions[str(n)]["title"])}</span></a>'
        )
    else:
        parts.append(
            '<a class="next" href="index.html">'
            '<span class="pager-dir">Finish &rarr;</span>'
            '<span class="pager-label">Back to overview</span></a>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def complete_toggle(meta):
    code = meta["code"]
    return (
        '<div class="session-complete" data-session-code="' + code + '">'
        '<button id="markComplete" type="button" class="mark-btn">'
        '<span class="mark-box">&#10003;</span> Mark '
        f'{code} complete</button>'
        '<span class="mark-hint">Progress is saved in your browser.</span>'
        "</div>"
    )


def builds_on_html(curriculum, meta):
    bo = meta.get("builds_on")
    if not bo:
        return (
            '<div class="builds-on builds-on--start">'
            '<span class="builds-on-tag">Start here</span> '
            "This is the first session — nothing to build on yet.</div>"
        )
    parent = curriculum["sessions"][str(bo)]
    return (
        '<div class="builds-on">'
        '<span class="builds-on-tag">Builds on</span> '
        f'<a href="session-{bo:02d}.html">{parent["code"]} · {_html.escape(parent["title"])}</a>'
        "</div>"
    )


# --------------------------------------------------------------------- builders
def build_session(curriculum, heroes, sid):
    sessions = curriculum["sessions"]
    meta = sessions[str(sid)]
    part = next(p for p in curriculum["parts"] if p["id"] == meta["part"])
    src = CONTENT / f"session-{sid:02d}.md"
    if not src.exists():
        raise FileNotFoundError(f"Missing content file: {src}")
    rendered, toc = render_markdown(src.read_text(encoding="utf-8"))

    opener = part_openers(curriculum).get(sid)
    hero = heroes.get("parts", {}).get(str(opener)) if opener else None

    crumbs = (
        f'<div class="crumbs">'
        f'<span class="crumb-part">{_html.escape(part["title"])}</span>'
        f'<span class="crumb-sep">·</span>'
        f'<span class="crumb-code">Session {meta["code"]}</span>'
        f'<span class="crumb-sep">·</span>'
        f'<span class="crumb-min">~{meta["minutes"]} min</span>'
        f"</div>"
    )
    body = (
        hero_html(hero)
        + crumbs
        + builds_on_html(curriculum, meta)
        + rendered
        + complete_toggle(meta)
        + prev_next_html(curriculum, sid)
    )
    title = seo.seo_title(f"{meta['code']} {meta['title']} · Apigee X for Spring Boot Developers")
    seo_head = seo.head_block(f"session-{sid:02d}.html", title, meta.get("objective", ""))
    html = page_shell(
        title,
        sidebar_html(curriculum, sid),
        body,
        total=len(sessions),
        toc_html=toc,
        session=sid,
        seo_head=seo_head,
    )
    (DOCS / f"session-{sid:02d}.html").write_text(html, encoding="utf-8")


def build_index(curriculum, heroes):
    rendered, _ = render_markdown((CONTENT / "index.md").read_text(encoding="utf-8"))
    body = hero_html(heroes.get("splash")) + rendered
    title = seo.seo_title(f"{curriculum['title']} · {curriculum['subtitle']}", is_index=True)
    html = page_shell(
        title,
        sidebar_html(curriculum, active_id=0),
        body,
        total=len(curriculum["sessions"]),
        is_index=True,
        seo_head=seo.head_block("index.html", title),
    )
    (DOCS / "index.html").write_text(html, encoding="utf-8")


def write_pygments_css():
    css = HtmlFormatter(style=ApolakiStyle).get_style_defs(".codehilite")
    (DOCS / "assets" / "pygments.css").write_text(css, encoding="utf-8")


def write_curriculum_json(curriculum):
    """Expose the curriculum to the client (used by the curriculum-map widget)."""
    (DOCS / "assets" / "curriculum.json").write_text(
        json.dumps(curriculum), encoding="utf-8"
    )


def main():
    curriculum = load_curriculum()
    heroes = load_heroes()
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)

    # Copy the whole assets tree (style/js + svg/ + heroes/) verbatim, then add
    # the generated pygments.css and curriculum.json on top.
    shutil.copytree(ASSETS, DOCS / "assets")
    write_pygments_css()
    write_curriculum_json(curriculum)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")  # serve files verbatim

    build_index(curriculum, heroes)
    count = 0
    for sid in session_order(curriculum):
        build_session(curriculum, heroes, sid)
        count += 1
    print(f"Built index + {count} session pages into {DOCS}")


if __name__ == "__main__":
    main()
