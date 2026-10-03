#!/usr/bin/env python3
"""
Pre-render static HTML into the JS-filled containers of the public pages, so
crawlers that do not run JavaScript (most AI crawlers) read real content.

Each block sits between marker comments INSIDE the container the page's JS
fills; the JS replaces it on load. Markup and labels mirror what the page JS
builds from the same data/*.json. Headline counts and top-10 rows only, never
the full directory. The block is never hidden.

    <!-- static:<id>:start -->
    ...
    <!-- static:<id>:end -->

Idempotent. Raises if a page's markers are missing. Run after the JSON builds
(refresh_state_capacity.yml does). Copy logic of inject() is from the data
site's seo/static_snapshot.py (this repo cannot import from it).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TOP = 10


# ── marker injection (same convention as the data site's static_snapshot.py) ──

def markers(block_id):
    return f"<!-- static:{block_id}:start -->", f"<!-- static:{block_id}:end -->"


def inject(path, block_id, html):
    """Replace the content between the block's markers in `path`. Returns True
    when the file changed."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    start, end = markers(block_id)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"{path}: markers for static block '{block_id}' not found; add\n  {start}\n  {end}\n"
                         f"inside the container the page's JS fills")
    new = pattern.sub(lambda _m: f"{start}\n{html}\n{end}", text, count=1)
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False


# ── helpers mirroring the page JS ──

def esc(s):
    return (str(s) if s else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def lower_key(v):
    return (str(v) if v else "").lower()


SEGMENT_COLORS = {
    "Research": "#2563eb", "Government": "#0891b2", "Philanthropy": "#dc2626", "Fellowships": "#d97706",
    "Community": "#7c3aed", "GovTech": "#16a34a", "Advocacy": "#db2777",
    "Digital Services & Consulting": "#0d9488", "Investor": "#9333ea",
    "Capacity Building": "#ca8a04", "Ecosystems": "#65a30d",
}  # same map as the organizations and affinity-map pages


def norm_area(a):
    return "Domains" if a == "Verticals" else a


DASH_FAINT = '<span class="funder-mini" style="color:var(--text-faint)">—</span>'


# ── blocks ──

def community_latest_writing():
    posts = sorted(load("substack_posts.json"), key=lambda p: p["date"], reverse=True)[:3]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    out = []
    for p in posts:
        y, m = p["date"].split("-")[:2]
        sub = f"<p>{esc(p['subtitle'])}</p>" if p.get("subtitle") else ""
        out.append(f'<div class="lw-post"><a class="t" href="{esc(p["url"])}" target="_blank" rel="noopener">{esc(p["title"])}</a>'
                   f'{sub}<div class="d">{months[int(m) - 1]} {y}</div></div>')
    return "\n".join(out)


SOURCE_LABELS = {
    "civic-tech-build-night": "State Capacity Hackathon: A Civic Tech Build Night · June 2026",
    "sce-team": "SCE team",
    "public-engagement": "State Capacity Hackathon: Public Engagement · Sept 2026",
}


def proof_points_grid():
    out = []
    for tl in load("proof_points.json")[:TOP]:
        hosted = bool(tl.get("hosted"))
        attrs = "" if hosted else ' target="_blank" rel="noopener"'
        thumb = ""
        if tl.get("image"):
            alt = esc("Screenshot of " + (tl.get("handle") or tl["name"]))
            thumb = f'<div class="tool-thumb"><img alt="{alt}" loading="lazy" width="640" height="360" src="{esc(tl["image"])}"></div>'
        handle = f'<div class="tool-handle">{esc(tl["handle"])}</div>' if tl.get("handle") and tl["handle"] != tl["name"] else ""
        credit = f'<div class="tool-credit">By {esc(tl["builders"])}</div>' if tl.get("builders") else ""
        out.append(
            f'<a class="tool-card" href="{esc(tl["url"])}"{attrs}>{thumb}'
            f'<div class="tool-kicker">{esc(SOURCE_LABELS.get(tl["source"], tl["source"]))}</div>'
            f'<div class="tool-title">{esc(tl["name"])}</div>{handle}'
            f'<div class="tool-desc">{esc(tl.get("blurb"))}</div>'
            f'<div class="tool-tags"><span class="tool-tag">{"Hosted here" if hosted else "External"}</span>'
            f'<span class="tool-tag">{esc(tl["problem_area"])}</span></div>{credit}'
            f'<div class="tool-cta">{"Open the tool →" if hosted else "Open the tool ↗"}</div></a>')
    return "\n".join(out)


def tags(items, cls, limit, more_cls="funder-mini", empty=DASH_FAINT):
    if not items:
        return empty
    s = "".join(f'<span class="{cls}">{esc(i)}</span>' for i in items[:limit])
    if len(items) > limit:
        s += f' <span class="{more_cls}">+{len(items) - limit}</span>'
    return s


def orgs_count():
    return f"Showing <strong>{min(TOP, len(load('directory.json')))}</strong> of <strong>{len(load('directory.json'))}</strong> organizations"


def orgs_rows():
    orgs = sorted(load("directory.json"), key=lambda o: lower_key(o.get("name")))[:TOP]
    out = []
    for o in orgs:
        sunset = o.get("status") == "sunset"
        color = SEGMENT_COLORS.get(o.get("primary_segment"), "#6b7280")
        raw = o.get("description") or ""
        trunc = raw[:180].rstrip() + "…" if len(raw) > 180 else raw
        desc = f'<div class="desc-text">{esc(trunc)}</div>' if raw else DASH_FAINT
        areas = [norm_area(a) for a in o.get("problem_areas") or []]
        name_style = ' style="color:var(--text-faint)"' if sunset else ""
        sun = ' <span class="seg-tag secondary" style="background:#f3f4f6;color:var(--text-faint)">Sunset</span>' if sunset else ""
        out.append(
            f'<tr class="data-row" data-id="{o["id"]}">\n'
            f'    <td class="name-cell"><div class="org-name"{name_style}>{esc(o["name"])}</div></td>\n'
            f'    <td><span class="seg-tag" style="background:{color}">{esc(o.get("primary_segment"))}</span>{sun}</td>\n'
            f'    <td class="desc-cell">{desc}</td>\n'
            f'    <td class="tag-cell">{tags(areas, "area-tag", 3)}</td>\n'
            f'    <td class="tag-cell">{tags(o.get("problem_statements") or [], "problem-tag", 3)}</td>\n'
            f'    <td style="text-align:center"><span class="expand-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></span></td>\n'
            f'  </tr>')
    return "\n".join(out)


ROLE_CLASS = {
    "Advocate": "advocate", "Capacity Builder": "capacity", "Fellowship Program": "fellowship",
    "Funder": "funder", "Government Practitioner": "govpractitioner", "Government practitioner": "govpractitioner",
    "Media": "media", "Other": "other", "Researcher": "researcher",
}


def split_list(v, alt=None):
    if v:
        return v if isinstance(v, list) else [s.strip() for s in v.split(", ")]
    return [alt] if alt else []


def people_count():
    n = len(load("connect.json"))
    return f"Showing <strong>{min(TOP, n)}</strong> of <strong>{n}</strong> entries"


def people_rows():
    people = sorted(load("connect.json"), key=lambda p: lower_key(p.get("name")))[:TOP]
    dir_by_name = {}
    for o in load("directory.json"):
        dir_by_name.setdefault(lower_key(o.get("name")), o)
    empty = '<span class="empty-cell">—</span>'
    out = []
    for p in people:
        role = p.get("role")
        role_html = f'<span class="role-tag {ROLE_CLASS.get(role, "")}">{esc(role)}</span>' if role else empty

        def cell(items, cls, limit):
            if not items:
                return empty
            s = "".join(f'<span class="{cls}">{esc(i)}</span>' for i in items[:limit])
            if len(items) > limit:
                s += f' <span class="empty-cell">+{len(items) - limit}</span>'
            return s

        offs = split_list(p.get("offering"), p.get("help_source"))
        areas = split_list(p.get("problem_areas"), p.get("problem_area"))
        topics = split_list(p.get("problem_topics"), p.get("problem_topic"))
        due = p.get("due_by") or p.get("time_window")
        due_html = f'<span class="time-tag">{esc(due)}</span>' if due else empty
        org = p.get("organization")
        org_html = ""
        if org:
            d = dir_by_name.get(org.lower())
            org_html = (f'<a href="/ecosystem/organizations/?org={d["id"]}" style="color:inherit;text-decoration:underline">{esc(org)}</a>'
                        if d else esc(org))
        # Contact cell: facilitated entries show the intro link text; direct
        # contacts (often personal emails) are left to the live page.
        contact = '<a href="/ecosystem/connect/" class="contact-ir">Request intro →</a>' if p.get("contact_preference") == "Facilitated" else ""
        out.append(
            f'<tr class="data-row" data-id="{p["id"]}">\n'
            f'    <td class="name-cell">\n      <div class="entry-name">{esc(p["name"])}</div>\n      <div class="entry-org">{org_html}</div>\n    </td>\n'
            f'    <td>{role_html}</td>\n    <td>{cell(offs, "help-tag", 2)}</td>\n    <td>{cell(areas, "area-tag", 2)}</td>\n'
            f'    <td>{cell(topics, "topic-tag", 2)}</td>\n    <td>{due_html}</td>\n'
            f'    <td class="contact-cell">{contact}</td>\n'
            f'    <td style="text-align:center"><span class="expand-icon">›</span></td>\n  </tr>')
    return "\n".join(out)


def change_feed():
    entries = (load("changes.json") or {}).get("entries") or []
    if not entries:
        return '<div class="cf-row"><span class="cf-empty">No changes recorded yet. The directory refreshes daily.</span></div>'
    out = []
    for e in entries[:3]:
        c = e["counts"]
        parts = []
        if c.get("added"):
            parts.append(f'{c["added"]} added')
        if c.get("removed"):
            parts.append(f'{c["removed"]} removed')
        if c.get("edited"):
            parts.append(f'{c["edited"]} updated')
        names = e.get("added") or []
        chips = "".join(f'<a class="cf-chip" href="/ecosystem/organizations/?q={quote(n)}">{esc(n)}</a>' for n in names[:6])
        more = (f'<span class="cf-chip" style="background:transparent;border-style:dashed;">+{len(names) - 6} more</span>'
                if len(names) > 6 else "")
        out.append(f'<div class="cf-row">\n        <span class="cf-date">{esc(e["date"])}</span>\n'
                   f'        <span class="cf-summary">{esc(", ".join(parts))}</span>\n'
                   f'        <span class="cf-chips">{chips}{more}</span>\n      </div>')
    return "".join(out)


def quote(s):
    from urllib.parse import quote as q
    return q(s, safe="-_.!~*'()")  # same set as JS encodeURIComponent


def seg_chips():
    nodes = load("affinity.json")["nodes"]
    counts = {}
    for n in nodes:
        counts[n["primary_segment"]] = counts.get(n["primary_segment"], 0) + 1
    segs = sorted(counts, key=lambda s: -counts[s])  # stable, as the page's sort
    out = []
    for s in segs:
        c = SEGMENT_COLORS.get(s, "#6b7280")
        out.append(f'<div class="seg-chip" data-seg="{esc(s)}" style="border-color:{c}; color:{c}">'
                   f'<span class="swatch" style="background:{c}"></span>{esc(s)} '
                   f'<span style="opacity:0.55;font-weight:500">{counts[s]}</span></div>')
    return "\n".join(out)


def stat(key):
    s = load("affinity.json")["stats"]
    if key == "mutual_count":
        return f'{s["mutual_count"]:,}'
    return f'{round(s["cross_share"] * 100)}%'


BLOCKS = [
    ("community/index.html", "latest-writing", community_latest_writing),
    ("community/proof-points/index.html", "proof-points-grid", proof_points_grid),
    ("ecosystem/organizations/index.html", "orgs-count", orgs_count),
    ("ecosystem/organizations/index.html", "orgs-rows", orgs_rows),
    ("ecosystem/connect/index.html", "connect-count", people_count),
    ("ecosystem/connect/index.html", "connect-rows", people_rows),
    ("ecosystem/index.html", "change-feed", change_feed),
    ("ecosystem/methodology/index.html", "stat-mutual", lambda: stat("mutual_count")),
    ("ecosystem/methodology/index.html", "stat-cross", lambda: stat("cross_pct")),
    ("ecosystem/affinity-map/index.html", "segment-chips", seg_chips),
]


def main():
    changed = []
    for rel, block_id, fn in BLOCKS:
        if inject(ROOT / rel, block_id, fn()):
            changed.append(f"{rel}:{block_id}")
    print("changed:", ", ".join(changed) if changed else "nothing")


if __name__ == "__main__":
    main()
