#!/usr/bin/env python3
"""
Write the shared header and footer onto every chrome page, and keep each page's
<head> wired to the shared design system (assets/sce.css, assets/sce-nav.js,
Carlito). The header and footer below are the single source; edit them here
and rerun:

    python3 data/sync_chrome.py          # rewrite pages in place
    python3 data/sync_chrome.py --check  # exit 1 if any page is out of sync

A chrome page is any index.html that carries the header (or the pre-Oct-2026
ribbon) and is not a redirect stub. Hosted third-party tools have no header and
are never touched. The active nav item is set from the page's path.
Since Oct 15 2026 (Henry's homepage redesign, README decision #30).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SLACK = "https://airtable.com/app4aVWTmY27Uxcd2/pagYnmFXPMLRIeAiq/form"
CONTACT = "https://airtable.com/app4aVWTmY27Uxcd2/pagKzB4dnNljmrliZ/form"
SUBSTACK = "https://substack.statecapacityecosystem.com/"

LOGO = ('<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" fill="none" stroke="#1A1918" stroke-width="1.6">'
        '<circle cx="6" cy="8" r="3"></circle><circle cx="22" cy="6" r="3"></circle>'
        '<circle cx="14" cy="21" r="3.5" fill="#D4A853" stroke="#1A1918"></circle>'
        '<path d="M8.5 9.5l3.6 8.6M19.6 8.2l-4 9.6M9 7.6l10-1.2"></path></svg>')

SECTIONS = [
    ("ecosystem", "Ecosystem", "/ecosystem/", [
        ("/ecosystem/search/", "Search", "Find who's working on your problem."),
        ("/ecosystem/organizations/", "Organization Directory", "300+ organizations helping government deliver."),
        ("/ecosystem/connect/", "Connect", "People and open opportunities. Add yourself."),
        ("/ecosystem/affinity-map/", "Affinity Map", "What organizations have in common."),
    ]),
    ("events", "Events", "/events/", [
        ("/events/hackathons/", "Hackathons", "Build nights that end in working software."),
        ("/events/demo-nights/", "Demo Nights", "What got built, in front of the people who can adopt it."),
        ("/events/salons/", "Salons &amp; Meet-ups", "Small evenings on what the field needs."),
        ("/events/sponsors-checklist/", "Host or Sponsor an Event", "What hosts and sponsors own, on one page."),
    ]),
    ("community", "Community", "/community/", [
        ("/community/slack/", "Slack", "Meet people between events."),
        (SUBSTACK, "Substack ↗", "Essays from people doing the work."),
        ("/community/playbooks/", "Playbooks", "Run our formats in your own city."),
        ("/community/proof-points/", "Proof Points", "Every tool built through SCE."),
    ]),
    ("about", "About", "/about/", []),
]


def header(active):
    items = []
    for key, label, href, subs in SECTIONS:
        cls = "nav-link active" if key == active else "nav-link"
        if not subs:
            items.append(f'    <div class="nav-item"><a class="{cls}" href="{href}">{label}</a></div>')
            continue
        drop = []
        for h, l, d in subs:
            ext = ' target="_blank" rel="noopener"' if h.startswith("http") else ""
            drop.append(f'        <a href="{h}"{ext}>{l}<small>{d}</small></a>')
        items.append(f'    <div class="nav-item">\n      <a class="{cls}" href="{href}">{label} <span class="nav-caret" aria-hidden="true">▾</span></a>\n'
                     f'      <div class="nav-drop">\n' + "\n".join(drop) + '\n      </div>\n    </div>')
    return ('<header class="site-header">\n  <div class="site-header-inner">\n'
            f'    <a class="site-brand" href="/">{LOGO}<span>State Capacity Ecosystem</span></a>\n'
            '    <nav class="site-nav" aria-label="Main">\n' + "\n".join(items) + "\n"
            f'    <a class="nav-cta" href="{SLACK}" target="_blank" rel="noopener">Join the Slack</a>\n'
            '    </nav>\n  </div>\n</header>')


FOOTER = ('<footer class="site-footer">\n  <div class="site-footer-inner">\n    <div>\n'
          '      <div class="site-footer-name">State Capacity Ecosystem</div>\n'
          '      <div class="site-footer-tag">Connecting the people making government work better.</div>\n'
          '    </div>\n    <nav aria-label="Footer">\n'
          '      <a href="/ecosystem/">Ecosystem</a>\n      <a href="/events/">Events</a>\n'
          '      <a href="/community/">Community</a>\n      <a href="/about/">About</a>\n'
          f'      <a href="{SUBSTACK}" target="_blank" rel="noopener">Substack ↗</a>\n'
          f'      <a href="{CONTACT}" target="_blank" rel="noopener">Get in touch ↗</a>\n'
          '    </nav>\n  </div>\n</footer>')

FONT_LINK = ('<link href="https://fonts.googleapis.com/css2?family=Carlito:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">')
HEAD_TAIL = '<link rel="stylesheet" href="/assets/sce.css">\n<script src="/assets/sce-nav.js" defer></script>\n'

OLD_STYLE_IDS = ("ribbon-css", "ribbon-sub-css", "link-ux-css", "event-banner-css")
FONT_REPLACEMENTS = [
    (re.compile(r"""(['"]?)Roboto Mono\1\s*,\s*monospace"""), "Carlito, Calibri, sans-serif"),
    (re.compile(r"""'Inter'\s*,\s*-apple-system\s*,\s*BlinkMacSystemFont\s*,\s*(?:'Segoe UI'\s*,\s*)?sans-serif"""), "Carlito, Calibri, sans-serif"),
    (re.compile(r"""(['"]?)Inter\1\s*,\s*sans-serif"""), "Carlito, Calibri, sans-serif"),
    (re.compile(r"""(['"]?)Roboto Mono\1(?=[;"'}])"""), "Carlito, Calibri, sans-serif"),
]


def section_for(rel):
    first = rel.split("/")[0]
    return first if first in {"ecosystem", "events", "community", "about"} else ""


def chrome_pages():
    out = []
    for p in sorted(ROOT.rglob("index.html")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(".git/"):
            continue
        t = p.read_text(encoding="utf-8")
        if 'http-equiv="refresh"' in t:
            continue
        if '<nav class="ribbon"' in t or '<header class="site-header"' in t:
            out.append(p)
    return out


def sync(text, rel):
    t = text
    for sid in OLD_STYLE_IDS:
        t = re.sub(r'\s*<style id="%s">.*?</style>' % re.escape(sid), "", t, flags=re.S)
    t = re.sub(r'\s*<script id="ribbon-touch-js">.*?</script>', "", t, flags=re.S)
    t = re.sub(r'<link href="https://fonts\.googleapis\.com/css2\?family=[^"]*" rel="stylesheet">', FONT_LINK, t, count=1)
    for rx, rep in FONT_REPLACEMENTS:
        t = rx.sub(rep, t)
    t = t.replace(HEAD_TAIL, "")
    t = t.replace("</head>", HEAD_TAIL + "</head>", 1)
    hdr = header(section_for(rel))
    t, n = re.subn(r'<nav class="ribbon".*?</nav>', hdr, t, count=1, flags=re.S)
    if not n:
        t = re.sub(r'<header class="site-header">.*?</header>', hdr, t, count=1, flags=re.S)
    t, n = re.subn(r'<footer class="sce-footer">.*?</footer>', FOOTER, t, count=1, flags=re.S)
    if not n:
        t = re.sub(r'<footer class="site-footer">.*?</footer>', FOOTER, t, count=1, flags=re.S)
    return t


def main():
    check = "--check" in sys.argv
    stale = []
    for p in chrome_pages():
        rel = p.relative_to(ROOT).as_posix()
        old = p.read_text(encoding="utf-8")
        new = sync(old, rel)
        if new != old:
            stale.append(rel)
            if not check:
                p.write_text(new, encoding="utf-8")
    verb = "out of sync" if check else "updated"
    print(f"{len(stale)} page(s) {verb}" + (": " + ", ".join(stale) if stale else ""))
    if check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
