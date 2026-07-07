"""Native SEO head-block generator, imported by build.py.

Emits a managed <!-- SEO:START -->...<!-- SEO:END --> block containing canonical,
meta description, keywords, robots, author, favicon, Open Graph, Twitter card and
JSON-LD (Course/LearningResource + BreadcrumbList) for each generated page.

Canonical + og:url + og:image point at the aggregation hub (apigee-courses) so the
two published copies of this course consolidate to one canonical URL instead of
competing as duplicate content. Nothing here needs external packages.
"""
import html, json

# ============================ per-course config ============================
HUB_BASE      = "https://sreenivas-sadhu-prabhakara.github.io/apigee-courses"
COURSE_PATH   = 'spring-boot-devs'
COURSE_NAME   = 'Apigee X for Spring Boot Developers'
OG_IMAGE      = 'og-spring.png'
WORKLOAD      = 'PT33H'
INDEX_DESC    = 'Master Apigee X across 33 sessions that bridge every gateway concept to Spring Boot, taught through UK Open Banking and the FAPI security profile.'
BASE_KEYWORDS = ['apigee x', 'spring boot', 'api gateway', 'java developers', 'fapi', 'open banking']
SITE          = "Apigee X Training Hub"
AUTHOR        = "Sreenivas Sadhu Prabhakara"
FAVICON       = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 38 38'%3E%3Crect x='2' y='2' width='34' height='34' rx='5' fill='%230a0e12'/%3E%3Cpath d='M9 13.5h20M9 24.5h20' stroke='%232bf5c8' stroke-width='1.6' opacity='0.4'/%3E%3Cpath d='M19 6v26' stroke='%232bf5c8' stroke-width='2.4'/%3E%3Ccircle cx='19' cy='19' r='4' fill='%230a0e12' stroke='%232bf5c8' stroke-width='2.4'/%3E%3C/svg%3E"
# ==========================================================================

_PERSON = {"@type": "Person", "name": AUTHOR}
_ORG    = {"@type": "Organization", "name": SITE, "url": HUB_BASE + "/"}


def _attr(s):
    return (s.replace("&", "&amp;").replace('"', "&quot;")
             .replace("<", "&lt;").replace(">", "&gt;"))


def _ld(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _trim(text, n=155):
    text = " ".join((text or "").split()).strip().rstrip(".")
    if len(text) <= n:
        return text
    cut = text[:n]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(",;: ")


def _crumb(items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": u}
        for i, (n, u) in enumerate(items)]}


def head_block(filename, title, description=None):
    """Return the indented SEO <head> block for one generated page.

    filename: output file name, e.g. "index.html", "day-01.html", "session-07.html"
    title:    the page's <title> text (may contain HTML entities)
    description: raw per-page description (e.g. curriculum objective); ignored for index
    """
    course_url = HUB_BASE + "/" + COURSE_PATH + "/"
    is_index = (filename == "index.html")
    url = course_url if is_index else course_url + filename
    text_title = html.unescape(title)
    og_img = HUB_BASE + "/assets/og/" + OG_IMAGE

    if is_index:
        desc = _trim(INDEX_DESC, 160)
        keywords = list(BASE_KEYWORDS)
        og_type = "website"
        graph = [
            {"@type": "Course", "@id": course_url + "#course", "name": COURSE_NAME,
             "description": desc, "url": course_url, "provider": _ORG, "author": _PERSON,
             "inLanguage": "en", "isAccessibleForFree": True, "about": keywords,
             "offers": {"@type": "Offer", "category": "Free", "price": "0",
                        "priceCurrency": "USD", "availability": "https://schema.org/InStock"},
             "hasCourseInstance": {"@type": "CourseInstance", "courseMode": "Online",
                        "courseWorkload": WORKLOAD, "instructor": _PERSON}},
            _crumb([("Home", HUB_BASE + "/"), (COURSE_NAME, course_url)]),
        ]
    else:
        desc = _trim(description or text_title)
        keywords = list(BASE_KEYWORDS)
        og_type = "article"
        leaf = text_title.split(" · ")[0].strip()
        graph = [
            {"@type": "LearningResource", "@id": url + "#lesson", "name": text_title,
             "description": desc, "url": url, "inLanguage": "en", "isAccessibleForFree": True,
             "learningResourceType": "lesson", "teaches": keywords,
             "author": _PERSON, "provider": _ORG,
             "isPartOf": {"@type": "Course", "@id": course_url + "#course",
                          "name": COURSE_NAME, "url": course_url}},
            _crumb([("Home", HUB_BASE + "/"), (COURSE_NAME, course_url), (leaf, url)]),
        ]

    ld = {"@context": "https://schema.org", "@graph": graph}
    L = ["  <!-- SEO:START (managed by seo.py) -->"]
    L.append('  <link rel="canonical" href="%s">' % url)
    L.append('  <meta name="description" content="%s">' % _attr(desc))
    if keywords:
        L.append('  <meta name="keywords" content="%s">' % _attr(", ".join(keywords)))
    L.append('  <meta name="author" content="%s">' % _attr(AUTHOR))
    L.append('  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">')
    L.append('  <link rel="icon" href="%s">' % FAVICON)
    L.append('  <meta property="og:type" content="%s">' % og_type)
    L.append('  <meta property="og:site_name" content="%s">' % _attr(SITE))
    L.append('  <meta property="og:title" content="%s">' % title)
    L.append('  <meta property="og:description" content="%s">' % _attr(desc))
    L.append('  <meta property="og:url" content="%s">' % url)
    L.append('  <meta property="og:image" content="%s">' % og_img)
    L.append('  <meta property="og:image:width" content="1200">')
    L.append('  <meta property="og:image:height" content="630">')
    L.append('  <meta property="og:image:alt" content="%s">' % _attr(text_title))
    L.append('  <meta property="og:locale" content="en_US">')
    L.append('  <meta name="twitter:card" content="summary_large_image">')
    L.append('  <meta name="twitter:title" content="%s">' % title)
    L.append('  <meta name="twitter:description" content="%s">' % _attr(desc))
    L.append('  <meta name="twitter:image" content="%s">' % og_img)
    L.append('  <script type="application/ld+json">%s</script>' % _ld(ld))
    L.append("  <!-- SEO:END -->")
    return "\n".join(L)
