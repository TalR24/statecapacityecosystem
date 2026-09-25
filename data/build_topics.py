#!/usr/bin/env python3
"""Generates ecosystem/topics/index.html and ecosystem/topics/<slug>/index.html
for every topic in data/taxonomy.json. Idempotent; deletes stale topic folders
not present in the current taxonomy. Run from the repo root."""

import json
import re
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS_DIR = ROOT / "ecosystem" / "topics"
METHOD_HTML = (ROOT / "ecosystem" / "methodology" / "index.html").read_text()

SEGMENT_COLORS = {
    "Research": "#2563eb",
    "Government": "#0891b2",
    "Philanthropy": "#dc2626",
    "Fellowships": "#d97706",
    "Community": "#7c3aed",
    "GovTech": "#16a34a",
    "Advocacy": "#db2777",
    "Digital Services & Consulting": "#0d9488",
    "Investor": "#9333ea",
    "Capacity Building": "#ca8a04",
    "Ecosystems": "#65a30d",
}

SOURCE_LABELS = {
    "sce-team": "SCE team",
    "civic-tech-build-night": "Civic Tech Build Night",
}


def esc(s):
    return html.escape(s or "", quote=True)


def http(url):
    if not url:
        return ""
    if re.match(r"^https?://", url):
        return url
    return "https://" + url


def source_label(s):
    if s in SOURCE_LABELS:
        return SOURCE_LABELS[s]
    return (s or "").replace("-", " ").title()


def truncate(text, limit):
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def truncate_words(text, limit):
    """Trim to at most `limit` chars at a word boundary, no ellipsis added."""
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip()


# ---------------------------------------------------------------------------
# Chrome extraction from the methodology page (re-read fresh each run so
# ribbon edits there propagate automatically).
# ---------------------------------------------------------------------------

def extract_between(text, start_marker, end_marker):
    i = text.index(start_marker)
    j = text.index(end_marker, i)
    return text[i:j]


def extract_block(text, pattern):
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        raise RuntimeError(f"chrome pattern not found: {pattern}")
    return m.group(0)


BASE_STYLE = extract_block(METHOD_HTML, r"<style>.*?</style>")
RIBBON_CSS = extract_block(METHOD_HTML, r'<style id="ribbon-css">.*?</style>')
EVENT_BANNER_CSS = extract_block(METHOD_HTML, r'<style id="event-banner-css">.*?</style>')
CHROME_TOP = extract_between(METHOD_HTML, "<body>", '<div class="breadcrumb">').replace("<body>", "").strip()
FOOTER = extract_block(METHOD_HTML, r'<footer class="sce-footer">.*?</footer>')
FONT_LINKS = extract_block(METHOD_HTML, r'<link href="https://fonts\.googleapis\.com/css2[^"]*"[^>]*>')
PRECONNECTS = "\n  ".join(re.findall(r'<link rel="preconnect"[^>]*>', METHOD_HTML))

PAGE_CSS = """
<style id="topics-css">
  .t-main { flex:1; padding:clamp(6px,1vw,12px) clamp(16px,4vw,48px) clamp(40px,6vw,64px); }
  .t-main-inner { max-width:1300px; margin:0 auto; }
  .t-kicker { font-family:'Roboto Mono',monospace; font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.1em; color:var(--orange); margin:8px 0 10px; }
  .t-h1 { font-family:'Roboto Mono',monospace; font-size:clamp(1.3rem,3.4vw,2rem); font-weight:700; color:var(--text); letter-spacing:-0.03em; line-height:1.2; margin-bottom:10px; }
  .t-deck { font-size:0.95rem; color:var(--text-muted); max-width:780px; line-height:1.6; margin-bottom:8px; }
  .t-lead { font-size:0.92rem; color:var(--text-mid); max-width:900px; line-height:1.7; margin-bottom:28px; }
  .t-section { margin:28px 0; max-width:100%; }
  .t-section h2 { font-family:'Roboto Mono',monospace; font-size:1.02rem; font-weight:700; color:var(--text); letter-spacing:-0.02em; margin-bottom:14px; }
  .t-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; max-width:100%; }
  .t-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow-sm); padding:16px 18px; max-width:100%; }
  .t-card-top { display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; margin-bottom:6px; }
  .t-card-name { font-size:0.95rem; font-weight:600; color:var(--text); text-decoration:none; }
  .t-card-name:hover { color:var(--blue); }
  .t-chip { font-family:'Roboto Mono',monospace; font-size:0.66rem; font-weight:700; padding:2px 8px; border-radius:10px; white-space:nowrap; }
  .t-chip-sunset { font-family:'Roboto Mono',monospace; font-size:0.66rem; font-weight:700; padding:2px 8px; border-radius:10px; white-space:nowrap; background:#f3f4f6; color:#6b7280; border:1px solid #d1d5db; }
  .t-card-desc { font-size:0.84rem; color:var(--text-mid); line-height:1.55; margin-bottom:8px; }
  .t-card-link { font-family:'Roboto Mono',monospace; font-size:0.75rem; font-weight:600; color:var(--blue); text-decoration:none; }
  .t-card-link:hover { text-decoration:underline; }
  .t-empty { font-size:0.9rem; color:var(--text-muted); margin-bottom:12px; }
  .t-btn { display:inline-flex; align-items:center; gap:6px; font-family:'Roboto Mono',monospace; font-size:0.78rem; font-weight:700; text-decoration:none; padding:9px 16px; border-radius:7px; white-space:nowrap; border:1px solid #DFCEA1; background:#F5EDDA; color:#8A5F1E; transition:background .15s, color .15s; }
  .t-btn:hover { background:#8A5F1E; color:#fff; }
  .t-related { display:flex; flex-wrap:wrap; gap:8px; max-width:100%; }
  .t-related a { font-family:'Roboto Mono',monospace; font-size:0.8rem; font-weight:600; color:var(--blue); text-decoration:none; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:7px 12px; }
  .t-related a:hover { border-color:var(--blue); }
  .t-cta-band { background:var(--surface); border:1px solid var(--border); border-left:3px solid var(--orange); border-radius:8px; padding:20px 22px; margin-top:32px; display:flex; align-items:center; justify-content:space-between; gap:18px; flex-wrap:wrap; max-width:100%; }
  .t-cta-band p { font-size:0.92rem; color:var(--text-mid); margin:0; }
  .t-cta-actions { display:flex; gap:10px; flex-wrap:wrap; }
  .t-area-block { margin-bottom:32px; max-width:100%; }
  .t-area-block h2 { font-family:'Roboto Mono',monospace; font-size:1.05rem; font-weight:700; color:var(--text); margin-bottom:12px; }
  .t-topic-cols { columns:2; column-gap:28px; }
  .t-topic-row { break-inside:avoid; margin-bottom:14px; }
  .t-topic-row a { font-size:0.92rem; font-weight:600; color:var(--text); text-decoration:none; }
  .t-topic-row a:hover { color:var(--blue); }
  .t-topic-meta { display:block; font-family:'Roboto Mono',monospace; font-size:0.72rem; color:var(--text-faint); margin-top:2px; }
  html, body { max-width:100%; overflow-x:hidden; }
  * { max-width:100%; }
  @media (max-width:720px) {
    .t-grid { grid-template-columns:1fr; }
    .t-topic-cols { columns:1; }
  }
</style>
"""


def head(title, description, canonical, page_css_extra=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <link rel="icon" type="image/png" href="/assets/sce_logo.png">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{canonical}">
  <meta name="twitter:card" content="summary_large_image">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{canonical}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:image" content="https://statecapacityecosystem.com/assets/sce_logo.png">
  {PRECONNECTS}
  {FONT_LINKS}
  {BASE_STYLE}
{RIBBON_CSS}
{EVENT_BANNER_CSS}
{PAGE_CSS}
{page_css_extra}
</head>
<body>

{CHROME_TOP}
"""


def breadcrumb(trail):
    """trail: list of (label, href_or_None). Last item has href None (current)."""
    parts = []
    for i, (label, href) in enumerate(trail):
        if i:
            parts.append('<span class="breadcrumb-sep">/</span>')
        if href:
            parts.append(f'<a href="{href}">{esc(label)}</a>')
        else:
            parts.append(f'<span class="current">{esc(label)}</span>')
    return f'<div class="breadcrumb">\n  <div class="breadcrumb-inner">\n    {"".join(parts)}\n  </div>\n</div>\n'


def footer_and_close():
    return f"\n{FOOTER}\n\n</body>\n</html>\n"


# ---------------------------------------------------------------------------
# Data loading (read fresh every run)
# ---------------------------------------------------------------------------

def load_data():
    taxonomy = json.loads((ROOT / "data" / "taxonomy.json").read_text())
    directory = json.loads((ROOT / "data" / "directory.json").read_text())
    connect = json.loads((ROOT / "data" / "connect.json").read_text())
    proof_points = json.loads((ROOT / "data" / "proof_points.json").read_text())
    return taxonomy, directory, connect, proof_points


def build():
    taxonomy, directory, connect, proof_points = load_data()
    topics = taxonomy["topics"]
    areas = taxonomy["areas"]
    slugs = {t["slug"] for t in topics}

    TOPICS_DIR.mkdir(parents=True, exist_ok=True)

    # delete stale topic folders
    for child in TOPICS_DIR.iterdir():
        if child.is_dir() and child.name not in slugs:
            for f in child.glob("*"):
                f.unlink()
            child.rmdir()

    # precompute counts for every topic
    counts = {}
    for t in topics:
        name = t["topic"]
        orgs = [o for o in directory if name in (o.get("problem_statements") or [])]
        conn = [c for c in connect if name in (c.get("problem_topics") or [])]
        tools = [p for p in proof_points if p.get("problem_area") == t["area"]]
        counts[t["slug"]] = {"orgs": orgs, "connect": conn, "tools": tools}

    by_area = {}
    for t in topics:
        by_area.setdefault(t["area"], []).append(t)

    pages = 0
    for t in topics:
        build_topic_page(t, counts, by_area)
        pages += 1

    build_index_page(taxonomy, counts)
    pages += 1

    return pages


def org_card(o):
    segment = o.get("primary_segment", "")
    color = SEGMENT_COLORS.get(segment, "#6b7280")
    desc = truncate(o.get("description", ""), 200)
    website = o.get("website", "")
    sunset = o.get("status") == "sunset"
    link_html = f'<a class="t-card-link" href="{esc(http(website))}" target="_blank" rel="noopener">Website ↗</a>' if website else ""
    sunset_html = '<span class="t-chip-sunset">Sunset</span>' if sunset else ""
    return f"""<div class="t-card">
        <div class="t-card-top">
          <a class="t-card-name" href="/ecosystem/organizations/?org={o['id']}">{esc(o['name'])}</a>
          <span class="t-chip" style="background:{color}1a;color:{color};border:1px solid {color}55;">{esc(segment)}</span>
          {sunset_html}
        </div>
        <p class="t-card-desc">{esc(desc)}</p>
        {link_html}
      </div>"""


def connect_card(c):
    offering = c.get("offering") or []
    if isinstance(offering, str):
        offering = [offering]
    offering_txt = ", ".join(offering)
    return f"""<div class="t-card">
        <div class="t-card-top">
          <a class="t-card-name" href="/ecosystem/connect/?entry={c['id']}">{esc(c['name'])}</a>
        </div>
        <p class="t-card-desc">{esc(c.get('organization',''))}{' &middot; ' + esc(c.get('role','')) if c.get('role') else ''}</p>
        {f'<p class="t-card-desc">{esc(offering_txt)}</p>' if offering_txt else ''}
      </div>"""


def tool_card(p):
    return f"""<div class="t-card">
        <div class="t-card-top">
          <a class="t-card-name" href="{esc(p.get('url',''))}">{esc(p.get('name',''))}</a>
        </div>
        <p class="t-card-desc">{esc(p.get('blurb',''))}</p>
        <span class="t-card-link">{esc(source_label(p.get('source','')))}</span>
      </div>"""


def lead_sentence(topic_name, n, m, t):
    if n == 0 and m == 0 and t == 0:
        return "Nobody in the ecosystem carries this topic yet. Be the first."
    clauses = []
    if n:
        if n == 1:
            clauses.append(f"1 organization works on {topic_name}")
        else:
            clauses.append(f"{n} organizations work on {topic_name}")
    if m:
        if m == 1:
            clauses.append("1 person or opportunity on Connect carries it")
        else:
            clauses.append(f"{m} people or opportunities on Connect carry it")
    if t:
        if t == 1:
            clauses.append("1 tool in Proof Points touches its problem area")
        else:
            clauses.append(f"{t} tools in Proof Points touch its problem area")
    if len(clauses) == 1:
        return clauses[0] + "."
    if len(clauses) == 2:
        return clauses[0] + ", and " + clauses[1] + "."
    return clauses[0] + ", " + clauses[1] + ", and " + clauses[2] + "."


def build_topic_page(t, counts, by_area):
    slug = t["slug"]
    area = t["area"]
    topic = t["topic"]
    definition = t["definition"]
    c = counts[slug]
    orgs = sorted(c["orgs"], key=lambda o: (o.get("status") == "sunset", o.get("name", "").lower()))
    conn = c["connect"]
    tools = c["tools"]
    n, m, tt = len(orgs), len(conn), len(tools)

    title = f"{topic} — Ecosystem · State Capacity Ecosystem"
    n_txt = "1 organization" if n == 1 else f"{n} organizations"
    m_txt = "1 Connect entry" if m == 1 else f"{m} Connect entries"
    t_txt = "1 tool" if tt == 1 else f"{tt} tools"
    desc_full = f"{topic}: {definition} {n_txt}, {m_txt}, and {t_txt} in the State Capacity Ecosystem."
    if len(desc_full) <= 160:
        description = desc_full
    else:
        description = truncate_words(f"{topic}: {definition}", 160) + "…"
    canonical = f"https://statecapacityecosystem.com/ecosystem/topics/{slug}/"

    out = [head(title, description, canonical)]
    out.append(breadcrumb([
        ("State Capacity Ecosystem", "/"),
        ("Ecosystem", "/ecosystem/"),
        ("Problem topics", "/ecosystem/topics/"),
        (topic, None),
    ]))

    body = []
    body.append('<div class="t-main"><div class="t-main-inner">')
    body.append(f'<div class="t-kicker">{esc(area)}</div>')
    body.append(f'<h1 class="t-h1">{esc(topic)}</h1>')
    body.append(f'<p class="t-deck">{esc(definition)}</p>')
    body.append(f'<p class="t-lead">{esc(lead_sentence(topic, n, m, tt))}</p>')

    # Who works on it
    body.append('<div class="t-section"><h2>Who works on it</h2>')
    if orgs:
        body.append('<div class="t-grid">')
        body.extend(org_card(o) for o in orgs)
        body.append('</div>')
    else:
        body.append('<p class="t-empty">No organizations carry this topic yet.</p>')
    body.append('</div>')

    # Connect
    body.append('<div class="t-section"><h2>People and opportunities on Connect</h2>')
    if conn:
        body.append('<div class="t-grid">')
        body.extend(connect_card(x) for x in conn)
        body.append('</div>')
    else:
        body.append('<p class="t-empty">No one on Connect carries this topic yet.</p>')
        body.append('<a class="t-btn" href="/ecosystem/connect/?add=1">Add yourself to Connect →</a>')
    body.append('</div>')

    # Tools
    if tools:
        body.append('<div class="t-section"><h2>Tools built on this problem area</h2>')
        body.append('<div class="t-grid">')
        body.extend(tool_card(p) for p in tools)
        body.append('</div></div>')

    # Related topics
    related = [rt for rt in by_area[area] if rt["slug"] != slug]
    if related:
        body.append('<div class="t-section"><h2>Related topics</h2>')
        body.append('<div class="t-related">')
        for rt in related:
            rn = len(counts[rt["slug"]]["orgs"])
            body.append(f'<a href="/ecosystem/topics/{rt["slug"]}/">{esc(rt["topic"])} ({rn})</a>')
        body.append('</div></div>')

    # Closing CTA
    body.append(f"""<div class="t-cta-band">
      <p>Work on {esc(topic)}? Add yourself so the people here can find you.</p>
      <div class="t-cta-actions">
        <a class="t-btn" href="/ecosystem/connect/?add=1">Add yourself to Connect →</a>
        <a class="t-btn" href="/ecosystem/organizations/?add=1">Suggest an organization →</a>
      </div>
    </div>""")

    body.append('</div></div>')
    out.append("\n".join(body))
    out.append(footer_and_close())

    folder = TOPICS_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text("".join(out))


def build_index_page(taxonomy, counts):
    topics = taxonomy["topics"]
    title = "Problem topics — Ecosystem · State Capacity Ecosystem"
    description = ("The 36 problem topics the State Capacity Ecosystem tracks, from procurement reform to "
                    "AI in government, with the organizations, people, and tools working on each.")
    canonical = "https://statecapacityecosystem.com/ecosystem/topics/"

    out = [head(title, description, canonical)]
    out.append(breadcrumb([
        ("State Capacity Ecosystem", "/"),
        ("Ecosystem", "/ecosystem/"),
        ("Problem topics", None),
    ]))

    body = []
    body.append('<div class="t-main"><div class="t-main-inner">')
    body.append('<h1 class="t-h1">Problem topics</h1>')
    body.append('<p class="t-deck" style="margin-bottom:28px;">Every problem the ecosystem works on, and who is working on it.</p>')

    by_area = {}
    for t in topics:
        by_area.setdefault(t["area"], []).append(t)

    for area in taxonomy["areas"]:
        area_topics = by_area.get(area, [])
        body.append('<div class="t-area-block">')
        body.append(f'<h2>{esc(area)}</h2>')
        body.append('<div class="t-topic-cols">')
        for t in area_topics:
            c = counts[t["slug"]]
            n, m = len(c["orgs"]), len(c["connect"])
            body.append(f"""<div class="t-topic-row">
        <a href="/ecosystem/topics/{t['slug']}/">{esc(t['topic'])}</a>
        <span class="t-topic-meta">{n} org{'s' if n != 1 else ''} · {m} on Connect</span>
      </div>""")
        body.append('</div></div>')

    body.append('</div></div>')
    out.append("\n".join(body))
    out.append(footer_and_close())

    (TOPICS_DIR / "index.html").write_text("".join(out))


if __name__ == "__main__":
    n_pages = build()
    print(f"build_topics: generated {n_pages} pages under ecosystem/topics/")
