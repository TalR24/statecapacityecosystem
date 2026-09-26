#!/usr/bin/env python3
"""
Monthly site-health check for the State Capacity Ecosystem site.

Deterministic drift detector. Writes a Markdown report to stdout and to
site_health_report.md (untracked). Exits 1 when any HARD check fails, 0
otherwise. Run from the repo root:

    python3 data/site_health.py [--external]

A separate Claude routine reads the report for judgment work; this script
only reports facts.
"""
import argparse
import concurrent.futures
import datetime
import html as H
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN = "statecapacityecosystem.com"
LIVE_BASE = "https://statecapacityecosystem.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

TODAY = datetime.date.today()

# ── shared regexes ────────────────────────────────────────────────────────
ATTR_RE = re.compile(r'\b(href|src|action)\s*=\s*"([^"]*)"', re.IGNORECASE)
REFRESH_RE = re.compile(r'<meta\s+http-equiv=["\']refresh["\']\s+content=["\'][^"\']*url=([^"\'\s]+)', re.IGNORECASE)
TITLE_RE = re.compile(r'<title>(.*?)</title>', re.IGNORECASE | re.DOTALL)
DESC_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']', re.IGNORECASE)
CANON_RE = re.compile(r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']*)["\']', re.IGNORECASE)
OG_RE = lambda prop: re.compile(r'<meta\s+property=["\']og:%s["\']\s+content=["\']([^"\']*)["\']' % prop, re.IGNORECASE)
ROBOTS_RE = re.compile(r'<meta\s+name=["\']robots["\']\s+content=["\']([^"\']*)["\']', re.IGNORECASE)
FAVICON_RE = re.compile(r'<link\s+rel=["\']icon["\'][^>]*href=["\']([^"\']*)["\']', re.IGNORECASE)
COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)


def repo_rel(path):
    return os.path.relpath(path, ROOT)


def line_of(content, idx):
    return content.count("\n", 0, idx) + 1


def strip_comments_keep_lines(text):
    def repl(m):
        return "\n" * m.group(0).count("\n")
    return COMMENT_RE.sub(repl, text)


def find_html_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if ".git" in dirpath.split(os.sep):
            continue
        for f in filenames:
            if f.endswith(".html"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


HTML_FILES = find_html_files()
FILE_RAW = {}
FILE_CLEAN = {}  # comments stripped, line numbers preserved
for f in HTML_FILES:
    with open(f, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    FILE_RAW[f] = raw
    FILE_CLEAN[f] = strip_comments_keep_lines(raw)


def visible_text(raw):
    """Strip script, style, comments, title and meta tags; unescape entities."""
    s = strip_comments_keep_lines(raw)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<title>.*?</title>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<meta\b[^>]*>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    return H.unescape(s)


def resolve_internal(target, source_file):
    t = target.split("#")[0].split("?")[0]
    if t == "":
        return None
    parsed = urllib.parse.urlparse(t)
    if parsed.scheme in ("http", "https") and parsed.netloc in (DOMAIN, "www." + DOMAIN):
        t = parsed.path or "/"
    if t.startswith("/"):
        rel = t.lstrip("/")
    else:
        srcdir = os.path.dirname(source_file)
        rel = os.path.relpath(os.path.normpath(os.path.join(srcdir, t)), ROOT)
    if rel == "" or rel == ".":
        rel = "index.html"
    full = os.path.join(ROOT, rel)
    if rel.endswith("/") or (os.path.isdir(full) and not rel.endswith(".html")):
        rel = rel.rstrip("/") + "/index.html" if rel != "" else "index.html"
    return rel


def is_internal(target):
    if target.startswith("#") or target.startswith("mailto:") or target.startswith("tel:") or target.startswith("javascript:"):
        return "skip"
    if target.startswith("/"):
        return True
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme in ("http", "https"):
        return parsed.netloc in (DOMAIN, "www." + DOMAIN)
    if parsed.scheme in ("mailto", "tel", "javascript"):
        return "skip"
    return True


# ── stub detection (shared across checks) ──────────────────────────────────
STUBS = {}  # rel path -> info dict
for f in HTML_FILES:
    content = FILE_CLEAN[f]
    m = REFRESH_RE.search(content)
    if not m:
        continue
    target = m.group(1).strip()
    rel_source = repo_rel(f)
    resolved = resolve_internal(target, f)
    target_full = os.path.join(ROOT, resolved) if resolved else None
    target_exists = os.path.isfile(target_full) if target_full else False
    robots_m = ROBOTS_RE.search(content)
    has_noindex = bool(robots_m and "noindex" in robots_m.group(1).lower())
    canon_m = CANON_RE.search(content)
    canonical = canon_m.group(1) if canon_m else None
    STUBS[rel_source] = {
        "target_raw": target,
        "resolved": resolved,
        "target_exists": target_exists,
        "noindex": has_noindex,
        "canonical": canonical,
    }
STUB_PATHS = set(STUBS.keys())
NON_STUB_PAGES = sorted(
    repo_rel(f) for f in HTML_FILES
    if repo_rel(f) not in STUB_PATHS and repo_rel(f) != "404.html"
)

# ── report scaffolding ──────────────────────────────────────────────────────
report_sections = []  # list of (title, status, [bullets])
hard_fail_count = 0
warn_count = 0
check_count = 0


def add_section(title, hard, findings):
    """findings: list of strings. hard=True -> FAIL on any finding, else WARN."""
    global hard_fail_count, warn_count, check_count
    check_count += 1
    if findings:
        if hard:
            status = "FAIL"
            hard_fail_count += 1
        else:
            status = "WARN"
            warn_count += 1
    else:
        status = "PASS"
    report_sections.append((title, status, findings))


# ── 1. Internal links ────────────────────────────────────────────────────
def check_internal_links():
    findings = []
    for f in HTML_FILES:
        rel_f = repo_rel(f)
        content = FILE_CLEAN[f]
        # meta refresh targets too
        targets = []
        for m in ATTR_RE.finditer(content):
            targets.append((m.group(1), m.group(2), m.start()))
        rm = REFRESH_RE.search(content)
        if rm:
            targets.append(("meta-refresh", rm.group(1).strip(), rm.start()))
        for attr, target, pos in targets:
            if not target or "${" in target:
                continue
            kind = is_internal(target)
            if kind != True:
                continue
            resolved = resolve_internal(target, f)
            if resolved is None:
                continue
            full = os.path.join(ROOT, resolved)
            if not os.path.isfile(full):
                ln = line_of(content, pos)
                findings.append(f"{rel_f}:{ln} [{attr}=\"{target}\"] -> `{resolved}` does not exist")
    add_section("1. Internal links", True, findings)


# ── 2. Redirect stubs ────────────────────────────────────────────────────
def check_stubs():
    findings = []
    for rel_source in sorted(STUBS):
        info = STUBS[rel_source]
        resolved = info["resolved"]
        problems = []
        if not info["target_exists"]:
            problems.append(f"target `{info['target_raw']}` does not exist")
        if resolved in STUB_PATHS:
            problems.append("target is itself a stub")
        if not info["noindex"]:
            problems.append("missing <meta name=\"robots\" content=\"noindex\">")
        expected_canonical = None
        if resolved:
            expected_canonical = LIVE_BASE + "/" + resolved.rsplit("index.html", 1)[0]
        if info["canonical"] != expected_canonical:
            problems.append(f"canonical {info['canonical']!r} != target URL {expected_canonical!r}")
        if problems:
            findings.append(f"{rel_source}: " + "; ".join(problems))
    add_section("2. Redirect stubs", True, findings)


# ── 3. SEO head ───────────────────────────────────────────────────────────
def check_seo_head():
    findings = []
    for f in HTML_FILES:
        rel_f = repo_rel(f)
        if rel_f in STUB_PATHS or rel_f == "404.html":
            continue
        content = FILE_CLEAN[f]
        missing = []
        title_m = TITLE_RE.search(content)
        if not title_m or not title_m.group(1).strip():
            missing.append("title")
        desc_m = DESC_RE.search(content)
        if not desc_m or not desc_m.group(1).strip():
            missing.append("meta description")
        canon_m = CANON_RE.search(content)
        if not canon_m:
            missing.append("canonical")
        else:
            canon_url = canon_m.group(1)
            if rel_f == "index.html":
                expected = LIVE_BASE + "/"
            else:
                expected = LIVE_BASE + "/" + rel_f.rsplit("/index.html", 1)[0] + "/"
            if canon_url != expected:
                missing.append(f"canonical mismatch (has {canon_url}, expected {expected})")
        for prop in ["title", "description", "type", "url", "image"]:
            if not OG_RE(prop).search(content):
                missing.append(f"og:{prop}")
        fav_m = FAVICON_RE.search(content)
        if not fav_m:
            missing.append("favicon link")
        else:
            resolved = resolve_internal(fav_m.group(1), f)
            if resolved and not os.path.isfile(os.path.join(ROOT, resolved)):
                missing.append(f"favicon target missing ({fav_m.group(1)})")
        if missing:
            findings.append(f"{rel_f}: missing " + ", ".join(missing))
    add_section("3. SEO head", True, findings)


# ── 4. Sitemap ────────────────────────────────────────────────────────────
def check_sitemap():
    findings = []
    with open(os.path.join(ROOT, "sitemap.xml"), "r", encoding="utf-8") as fh:
        sitemap_content = fh.read()
    sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", sitemap_content)
    sitemap_paths = set()
    for u in sitemap_urls:
        p = urllib.parse.urlparse(u)
        rel = p.path.lstrip("/")
        if rel == "" or rel.endswith("/"):
            rel = rel + "index.html"
        sitemap_paths.add(rel)

    for p in NON_STUB_PAGES:
        if p not in sitemap_paths:
            findings.append(f"{p} not in sitemap.xml")

    for u in sitemap_urls:
        parsed = urllib.parse.urlparse(u)
        rel = parsed.path.lstrip("/")
        if rel == "" or rel.endswith("/"):
            rel = rel + "index.html"
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            findings.append(f"sitemap URL {u} -> `{rel}` does not exist")
        elif rel in STUB_PATHS:
            findings.append(f"sitemap URL {u} -> `{rel}` is a stub")

    with open(os.path.join(ROOT, "robots.txt")) as fh:
        robots_content = fh.read()
    if "sitemap.xml" not in robots_content.lower():
        findings.append("robots.txt does not reference sitemap.xml")

    add_section("4. Sitemap", True, findings)


# ── 5. Ribbon and footer ─────────────────────────────────────────────────
RIBBON_RE = re.compile(r'<nav class="ribbon".*?</nav>', re.DOTALL)
FOOTER_RE = re.compile(r'<footer class="sce-footer">.*?</footer>', re.DOTALL)
ACTIVE_CLASS_RE = re.compile(r'class="([^"]*)\bactive\b([^"]*)"')


def normalize_ribbon(block):
    def strip_active(m):
        cls = (m.group(1) + m.group(2)).replace("  ", " ").strip()
        return f'class="{cls}"' if cls else 'class=""'
    return ACTIVE_CLASS_RE.sub(strip_active, block)


def check_ribbon_footer():
    findings = []
    ribbons = {}
    footers = {}
    for f in HTML_FILES:
        rel_f = repo_rel(f)
        if rel_f in STUB_PATHS:
            continue
        raw = FILE_RAW[f]
        rm = RIBBON_RE.search(raw)
        if rm:
            ribbons[rel_f] = normalize_ribbon(rm.group(0))
        fm = FOOTER_RE.search(raw)
        if fm:
            footers[rel_f] = normalize_ribbon(fm.group(0))

    if ribbons:
        # majority block wins as the canonical baseline
        from collections import Counter
        counts = Counter(ribbons.values())
        canonical_ribbon = counts.most_common(1)[0][0]
        for rel_f, block in sorted(ribbons.items()):
            if block != canonical_ribbon:
                findings.append(f"{rel_f}: ribbon differs from the common block")
    if footers:
        from collections import Counter
        counts = Counter(footers.values())
        canonical_footer = counts.most_common(1)[0][0]
        for rel_f, block in sorted(footers.items()):
            if block != canonical_footer:
                findings.append(f"{rel_f}: footer differs from the common block")

    add_section("5. Ribbon and footer", True, findings)
    return set(ribbons.keys())


# ── 6. Stat strings vs data ──────────────────────────────────────────────
def check_stats(chrome_pages):
    findings = []
    aff = json.loads(open(os.path.join(ROOT, "data/affinity.json")).read())
    stats = aff["stats"]
    org_count = stats["org_count"]
    edge_count = stats["edge_count"]
    funder_coverage = stats.get("funder_coverage")

    meth_path = os.path.join(ROOT, "ecosystem/methodology/index.html")
    meth = open(meth_path).read()
    if funder_coverage is not None:
        expected = f"Approximately {funder_coverage} of {org_count} orgs"
        if expected not in meth:
            findings.append(f"ecosystem/methodology/index.html: funder-callout sentence does not read {expected!r}")
    expected_nodes = f"<strong>{org_count} nodes and {edge_count:,} edges</strong>"
    if expected_nodes not in meth:
        findings.append(f"ecosystem/methodology/index.html: dataset-stats sentence does not read {expected_nodes!r}")

    readme = open(os.path.join(ROOT, "README.md")).read()
    expected_readme_orgs = f"- {org_count} orgs, {edge_count:,} kept edges"
    if expected_readme_orgs not in readme:
        findings.append(f"README.md: missing line {expected_readme_orgs!r}")
    if funder_coverage is not None:
        expected_readme_funder = f"- Funder coverage: {funder_coverage}/{org_count} orgs"
        if expected_readme_funder not in readme:
            findings.append(f"README.md: missing line {expected_readme_funder!r}")

    # "300+ organizations" record band: floor(org_count/100)*100 must equal 300
    hundred = (org_count // 100) * 100
    if hundred != 300:
        findings.append(
            f"data/affinity.json org_count={org_count} now floors to {hundred}, not 300; "
            f"every '300+ organizations' copy instance (homepage, ecosystem dropdown) needs updating"
        )

    # Community-page-style kicker: "N TOOLS · M PLAYBOOKS · K POSTS" (found site-wide, not pinned to one page)
    proof_points = json.loads(open(os.path.join(ROOT, "data/proof_points.json")).read())
    substack_posts = json.loads(open(os.path.join(ROOT, "data/substack_posts.json")).read())
    playbooks_path = os.path.join(ROOT, "community/playbooks/index.html")
    playbooks_html = open(playbooks_path).read()
    playbook_cards = len(re.findall(r'<a class="tool-card" data-cat="playbook"', playbooks_html))

    kicker_re = re.compile(r"(\d+)\s*TOOLS\s*·\s*(\d+)\s*PLAYBOOKS\s*·\s*(\d+)\s*POSTS")
    kicker_hits = []
    for f in HTML_FILES:
        m = kicker_re.search(FILE_CLEAN[f])
        if m:
            kicker_hits.append((repo_rel(f), m))
    if not kicker_hits:
        findings.append("kicker pattern 'N TOOLS · M PLAYBOOKS · K POSTS' not found anywhere in the site")
    else:
        for rel_f, m in kicker_hits:
            n_tools, n_playbooks, n_posts = (int(x) for x in m.groups())
            if n_tools != len(proof_points):
                findings.append(f"{rel_f}: kicker says {n_tools} TOOLS, proof_points.json has {len(proof_points)}")
            if n_playbooks != playbook_cards:
                findings.append(f"{rel_f}: kicker says {n_playbooks} PLAYBOOKS, playbooks page has {playbook_cards} playbook cards")
            if n_posts != len(substack_posts):
                findings.append(f"{rel_f}: kicker says {n_posts} POSTS, substack_posts.json has {len(substack_posts)}")

    # "20 prototypes in one evening, 8 still live" vs proof points with source civic-tech-build-night
    cbn_count = sum(1 for p in proof_points if p.get("source") == "civic-tech-build-night")
    home = open(os.path.join(ROOT, "index.html")).read()
    m = re.search(r"(\d+)\s*</b><span>prototypes in one evening,\s*(\d+)\s*still live</span>", home)
    if m:
        n_still_live = int(m.group(2))
        if n_still_live != cbn_count:
            findings.append(
                f"index.html: '{n_still_live} still live' does not match {cbn_count} proof_points entries "
                f"with source civic-tech-build-night"
            )
    else:
        findings.append("index.html: '<n> prototypes in one evening, <m> still live' sentence not found")

    add_section("6. Stat strings vs data", True, findings)


# ── 7. Event date drift (WARN) ───────────────────────────────────────────
DATE_PHRASE_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2})(?:,\s*(\d{4}))?\b|"
    r"\b(\d{4}-\d{2}-\d{2})\b"
)
NEAR_WORDS = ("Sign up", "Upcoming", "NEXT", "Coming")
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_phrase(m):
    if m.group(3):
        try:
            return datetime.datetime.strptime(m.group(3), "%Y-%m-%d").date()
        except ValueError:
            return None
    phrase = m.group(1)
    year = m.group(2)
    mm = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2})", phrase)
    if not mm:
        return None
    mon_key = mm.group(1).lower()[:4] if mm.group(1).lower().startswith("sept") else mm.group(1).lower()[:3]
    month = MONTH_MAP.get(mon_key) or MONTH_MAP.get(mm.group(1).lower()[:3])
    if not month:
        return None
    day = int(mm.group(2))
    if year:
        try:
            return datetime.date(int(year), month, day)
        except ValueError:
            return None
    for y in (TODAY.year, TODAY.year + 1):
        try:
            d = datetime.date(y, month, day)
        except ValueError:
            continue
        if (TODAY - d).days <= 30:
            return d
    try:
        return datetime.date(TODAY.year, month, day)
    except ValueError:
        return None


def check_event_dates():
    findings = []
    scan_files = [
        os.path.join(ROOT, "index.html"),
        os.path.join(ROOT, "events/index.html"),
        os.path.join(ROOT, "events/hackathons/index.html"),
    ]
    for path in scan_files:
        if not os.path.isfile(path):
            continue
        rel = repo_rel(path)
        text = visible_text(FILE_RAW[path])
        for m in DATE_PHRASE_RE.finditer(text):
            window = text[max(0, m.start() - 200): m.start() + 200]
            if not any(w in window for w in NEAR_WORDS):
                continue
            d = parse_date_phrase(m)
            if d is None:
                continue
            if d < TODAY:
                findings.append(f"{rel}: {m.group(0)!r} is in the past (run date {TODAY.isoformat()})")

    # "Coming soon" pages whose last commit is stale
    for f in HTML_FILES:
        raw = FILE_RAW[f]
        if "Coming soon" not in raw:
            continue
        rel = repo_rel(f)
        try:
            out = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--", rel],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )
            ts = out.stdout.strip()
            if not ts:
                findings.append(f"{rel}: 'Coming soon' page has no git history")
                continue
            commit_date = datetime.datetime.fromtimestamp(int(ts)).date()
            age_days = (TODAY - commit_date).days
            if age_days > 120:
                findings.append(f"{rel}: 'Coming soon' page last committed {commit_date.isoformat()} ({age_days} days ago)")
        except Exception as e:
            findings.append(f"{rel}: could not read git history ({e})")

    add_section("7. Event date drift (WARN)", False, findings)


# ── 8. Latest band freshness (WARN) ──────────────────────────────────────
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def check_latest_band():
    findings = []
    home_path = os.path.join(ROOT, "index.html")
    home = FILE_RAW[home_path]
    mo_list_m = re.search(r'<div class="mo-list" id="mo-list">(.*?)</div>\s*</div>\s*</section>', home, re.DOTALL)
    band_dates = []
    if mo_list_m:
        for m in re.finditer(r'<span class="mo-date">([A-Za-z]+)\s+(\d{4})</span>', mo_list_m.group(1)):
            mon, year = m.group(1), int(m.group(2))
            if mon[:3] in MONTH_ABBR:
                band_dates.append(datetime.date(year, MONTH_ABBR.index(mon[:3]) + 1, 1))
    substack_posts = json.loads(open(os.path.join(ROOT, "data/substack_posts.json")).read())
    if not band_dates:
        findings.append("could not parse any month-year label out of #mo-list")
    elif substack_posts:
        newest_band = max(band_dates)
        for p in substack_posts:
            try:
                pd = datetime.datetime.strptime(p["date"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            pd_month = datetime.date(pd.year, pd.month, 1)
            if pd_month > newest_band:
                findings.append(f"newer post not in Latest band: {p['title']!r} ({p['date']}) — {p.get('url', '')}")
    add_section("8. Latest band freshness (WARN)", False, findings)


# ── 9. Data contracts ────────────────────────────────────────────────────
def parse_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


SEGMENTS = {
    "Advocacy", "Capacity Building", "Community", "Digital Services & Consulting",
    "Ecosystems", "Fellowships", "GovTech", "Government", "Investor", "Philanthropy", "Research",
}
FOCUS_VALUES = {"City", "State", "Federal", "Outside US"}
PROBLEM_AREAS = {
    "Participatory Democracy", "Procurement & Operations", "Service Delivery",
    "Talent & Hiring", "Technology & Data", "Test & Learn", "Domains",
}
PROBLEM_TOPICS = {
    "Civic Engagement", "Democracy Infrastructure", "Transparency & Accountability",
    "Operational Excellence", "Procurement Reform", "Reaction Time", "Regulatory & Administrative Burden",
    "Benefits Access", "Service Design",
    "Expert Contribution", "Hiring Architecture", "Hiring Process", "Talent Pipeline", "Workforce Development",
    "Data Integration", "Data Security", "Legacy Systems", "Shared Platforms",
    "Evidence Use", "Feedback Loops", "Iterative Learning", "Outcomes Measurement", "Scaling What Works",
    "AI in Government", "Broadband & Internet Connectivity", "Child Welfare", "Criminal Justice",
    "Crisis Response", "Economic Mobility", "Education Delivery", "Healthcare Access",
    "Housing & Land Use", "Permitting & Licensing", "Physical Infrastructure", "Public Health", "Tax & Revenue",
}
EMAIL_RE = re.compile(r"^[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}$")
BARE_URL_RE = re.compile(r"^(https?://)?[\w.\-]+(\.[a-zA-Z]{2,})+(/\S*)?$")


def check_data_contracts():
    findings = []
    dir_path = os.path.join(ROOT, "data/directory.csv")
    rows = parse_csv(dir_path)
    seen_names = {}
    for i, row in enumerate(rows, start=2):  # header is line 1
        name = (row.get("Org Name") or "").strip()
        if not name:
            findings.append(f"data/directory.csv:{i}: blank Org Name")
        else:
            seen_names.setdefault(name, []).append(i)
        seg = (row.get("Primary Segment") or "").strip()
        if seg and seg not in SEGMENTS:
            findings.append(f"data/directory.csv:{i}: Primary Segment {seg!r} not in the 11 segments")
        for foc in (row.get("Focus") or "").split(","):
            foc = foc.strip()
            if foc and foc not in FOCUS_VALUES:
                findings.append(f"data/directory.csv:{i}: Focus {foc!r} not in City/State/Federal/Outside US")
        for area in (row.get("Problem Area") or "").split(","):
            area = area.strip()
            if area and area not in PROBLEM_AREAS:
                findings.append(f"data/directory.csv:{i}: Problem Area {area!r} not in the 7 areas")
        for topic in (row.get("Problem Topic") or "").split(","):
            topic = topic.strip()
            if topic and topic not in PROBLEM_TOPICS:
                findings.append(f"data/directory.csv:{i}: Problem Topic {topic!r} not in the 36 topics")
        if not (row.get("Description") or "").strip():
            findings.append(f"data/directory.csv:{i}: empty Description")
        if not (row.get("Website") or "").strip():
            findings.append(f"data/directory.csv:{i}: empty Website")
    for name, lines in seen_names.items():
        if len(lines) > 1:
            findings.append(f"data/directory.csv: duplicate Org Name {name!r} at lines {lines}")

    conn_path = os.path.join(ROOT, "data/connect_submissions.csv")
    conn_rows = parse_csv(conn_path)
    for i, row in enumerate(conn_rows, start=2):
        contact = (row.get("Contact") or "").strip()
        if not contact:
            continue
        if " " in contact or "(" in contact or ")" in contact:
            findings.append(f"data/connect_submissions.csv:{i}: Contact {contact!r} has spaces/parentheses")
            continue
        if not (EMAIL_RE.match(contact) or BARE_URL_RE.match(contact)):
            findings.append(f"data/connect_submissions.csv:{i}: Contact {contact!r} is not an email or bare URL/domain")

    add_section("9. Data contracts", True, findings)

    warn_findings = []
    changes = json.loads(open(os.path.join(ROOT, "data/changes.json")).read())
    state_size = len(changes.get("state", {}))
    csv_rows = len(rows)
    if state_size != csv_rows:
        warn_findings.append(f"data/changes.json state has {state_size} entries, data/directory.csv has {csv_rows} rows")
    add_section("9b. Change-feed state size (WARN)", False, warn_findings)

    hard_findings2 = []
    proof_points = json.loads(open(os.path.join(ROOT, "data/proof_points.json")).read())
    for i, p in enumerate(proof_points):
        if not (p.get("url") or "").strip():
            hard_findings2.append(f"data/proof_points.json[{i}] ({p.get('name', '?')!r}): empty url")
        if p.get("hosted"):
            url = p.get("url", "")
            path = url.lstrip("/")
            if path and not path.endswith("index.html"):
                path = path.rstrip("/") + "/index.html" if path.endswith("/") or "." not in os.path.basename(path) else path
            full = os.path.join(ROOT, path)
            if not os.path.isfile(full):
                hard_findings2.append(f"data/proof_points.json[{i}] ({p.get('name', '?')!r}): hosted path {url} -> `{path}` does not exist")
    add_section("9c. Proof points hosted paths", True, hard_findings2)


# ── 10. Tokenizer sync ───────────────────────────────────────────────────
def extract_py_set(text, varname):
    m = re.search(rf'{varname}\s*=\s*set\("""(.*?)"""\.split\(\)\)', text, re.DOTALL)
    if m:
        return set(m.group(1).split())
    m = re.search(rf'{varname}\s*=\s*\{{([^}}]*)\}}', text)
    if m:
        return set(re.findall(r'"([^"]+)"', m.group(1)))
    return None


def extract_js_set(text, varname):
    m = re.search(rf'{varname}\s*=\s*new Set\("([^"]*)"\.split', text)
    if m:
        return set(m.group(1).split())
    m = re.search(rf'{varname}\s*=\s*new Set\(\[([^\]]*)\]\)', text)
    if m:
        return set(re.findall(r'"([^"]+)"', m.group(1)))
    return None


def extract_geo_map(text):
    m = re.search(r'GEO_FOCUS_MAP\s*=\s*\[(.*?)\];', text, re.DOTALL)
    if not m:
        return None
    entries = []
    for em in re.finditer(r'\{\s*terms:\s*\[([^\]]*)\]\s*,\s*focus:\s*"([^"]*)"\s*\}', m.group(1)):
        terms = tuple(sorted(re.findall(r'"([^"]+)"', em.group(1))))
        entries.append((terms, em.group(2)))
    return sorted(entries)


def check_tokenizer_sync():
    findings = []
    py_path = os.path.join(ROOT, "data/build_affinity.py")
    js1_path = os.path.join(ROOT, "assets/sce-search.js")
    js2_path = os.path.join(ROOT, "ecosystem/affinity-map/index.html")
    py = open(py_path).read()
    js1 = open(js1_path).read()
    js2 = open(js2_path).read()

    py_short = extract_py_set(py, "SHORT_TERMS")
    js1_short = extract_js_set(js1, "SHORT_TERMS")
    js2_short = extract_js_set(js2, "SHORT_TERMS")
    if not (py_short == js1_short == js2_short):
        findings.append(
            f"SHORT_TERMS differ: build_affinity.py={sorted(py_short or [])}, "
            f"sce-search.js={sorted(js1_short or [])}, affinity-map/index.html={sorted(js2_short or [])}"
        )

    py_stop = extract_py_set(py, "STOPWORDS")
    js1_stop = extract_js_set(js1, "STOPWORDS")
    js2_stop = extract_js_set(js2, "STOPWORDS")
    if js1_stop != js2_stop:
        findings.append(
            f"STOPWORDS differ between assets/sce-search.js and ecosystem/affinity-map/index.html: "
            f"symmetric difference = {sorted((js1_stop or set()) ^ (js2_stop or set()))}"
        )
    if py_stop != js1_stop:
        diff = sorted((py_stop or set()) ^ (js1_stop or set()))
        findings.append(
            f"STOPWORDS differ between data/build_affinity.py and the page tokenizers "
            f"({len(diff)} words not shared): {diff[:20]}{' ...' if len(diff) > 20 else ''}"
        )

    geo1 = extract_geo_map(js1)
    geo2 = extract_geo_map(js2)
    if geo1 != geo2:
        findings.append("GEO_FOCUS_MAP differs between assets/sce-search.js and ecosystem/affinity-map/index.html")

    add_section("10. Tokenizer sync", True, findings)


# ── 11. Copy rules ────────────────────────────────────────────────────────
HOSTED_TOOL_PAGES = {
    "community/substack/nyc-grocery-access-site-prototype/index.html",
    "community/substack/mamdani-ai-priorities/summons-navigator/index.html",
    "community/substack/mamdani-ai-priorities/housing-approval-pathway/index.html",
    "events/hackathons/civic-tech-build-night/tideline/index.html",
    "events/sponsors-checklist/index.html",
}
NOT_JUST_RE = re.compile(r"\bnot just\b|\bisn't just\b|\bnot only\b|\bisn't about\b|\bit's not about\b", re.IGNORECASE)
RETIRED_PATTERNS = [
    "Explore the Databases", "degree cap", "MIN_W", "Mad Libs", "I am a ", "seeking ",
    "Browse topics", "ecosystem/topics", "4 still live", "refreshed periodically", "TF-IDF cosine)",
]
LOREM_PATTERNS = ["lorem", "TODO", "TBD", "XXX"]
GLOSSARY_LINE_RE = re.compile(r"<li><strong>[^<]+</strong>\s*—")


def check_copy_rules():
    warn_findings = []
    hard_findings = []
    for f in HTML_FILES:
        rel_f = repo_rel(f)
        if rel_f in HOSTED_TOOL_PAGES:
            continue
        raw = FILE_RAW[f]
        text = visible_text(raw)

        # em dashes: allowed only inside glossary lines of the form
        # <li><strong>Term</strong> — definition</li>
        clean_no_comments = strip_comments_keep_lines(raw)
        clean_no_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", clean_no_comments, flags=re.DOTALL | re.IGNORECASE)
        clean_no_titlemeta = re.sub(r"<title>.*?</title>", " ", clean_no_script, flags=re.DOTALL | re.IGNORECASE)
        clean_no_titlemeta = re.sub(r"<meta\b[^>]*>", " ", clean_no_titlemeta, flags=re.IGNORECASE)
        li_glossary_spans = [
            (gm.start(), gm.end())
            for gm in re.finditer(r"<li><strong>[^<]*</strong>[^<]*—[^<]*</li>", clean_no_titlemeta, re.DOTALL)
        ]
        for m in re.finditer(r"—", clean_no_titlemeta):
            if any(s <= m.start() < e for s, e in li_glossary_spans):
                continue
            ln = line_of(clean_no_titlemeta, m.start())
            snippet = clean_no_titlemeta[max(0, m.start() - 40):m.start() + 40]
            snippet = re.sub(r"<[^>]+>", " ", snippet).strip()
            warn_findings.append(f"{rel_f}:{ln}: em dash in prose: ...{snippet}...")

        for m in NOT_JUST_RE.finditer(text):
            warn_findings.append(f"{rel_f}: retired framing {m.group(0)!r}")

        for pat in RETIRED_PATTERNS:
            if pat in text or pat in raw:
                hard_findings.append(f"{rel_f}: retired wording {pat!r}")

        for pat in LOREM_PATTERNS:
            if pat in text:
                warn_findings.append(f"{rel_f}: placeholder text {pat!r}")

    add_section("11a. Copy rules: retired wording", True, hard_findings)
    add_section("11b. Copy rules: em dashes / framing / placeholders (WARN)", False, warn_findings)


# ── 12. Live site (WARN, network) ────────────────────────────────────────
LIVE_PAGES = {
    "home": "/",
    "ecosystem": "/ecosystem/",
    "organizations": "/ecosystem/organizations/",
    "connect": "/ecosystem/connect/",
    "affinity-map": "/ecosystem/affinity-map/",
    "methodology": "/ecosystem/methodology/",
    "events": "/events/",
    "hackathons": "/events/hackathons/",
    "community": "/community/",
    "about": "/about/",
}


def check_url(url):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return (resp.status, resp.geturl(), None, None)
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 999):
                continue
            return (e.code, url, None, None)
        except Exception as e:
            if method == "HEAD":
                continue
            return (None, url, str(e), None)
    return (None, url, "failed both HEAD and GET", None)


def check_url_body(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except Exception as e:
        return None, str(e)


def check_live_site():
    findings = []
    for name, path in LIVE_PAGES.items():
        url = LIVE_BASE + path
        status, final_url, err, _ = check_url(url)
        if status != 200:
            findings.append(f"{name} ({url}): status {status if status else 'UNVERIFIED'}" + (f" ({err})" if err else ""))

    local_home_title_m = TITLE_RE.search(FILE_CLEAN[os.path.join(ROOT, "index.html")])
    local_home_title = local_home_title_m.group(1).strip() if local_home_title_m else None
    local_ribbon_m = RIBBON_RE.search(FILE_RAW[os.path.join(ROOT, "index.html")])
    local_ribbon = normalize_ribbon(local_ribbon_m.group(0)) if local_ribbon_m else None

    body, err = check_url_body(LIVE_BASE + "/")
    if body is None:
        findings.append(f"could not fetch live homepage to compare deploy freshness ({err})")
    else:
        live_title_m = TITLE_RE.search(body)
        live_title = live_title_m.group(1).strip() if live_title_m else None
        if live_title != local_home_title:
            findings.append(f"live homepage <title> {live_title!r} != local {local_home_title!r} (deploy may be stale)")
        live_ribbon_m = RIBBON_RE.search(body)
        live_ribbon = normalize_ribbon(live_ribbon_m.group(0)) if live_ribbon_m else None
        if live_ribbon != local_ribbon:
            findings.append("live homepage ribbon differs from local index.html ribbon (deploy may be stale)")

    add_section("12. Live site (WARN, network)", False, findings)


# ── 13. External links (WARN, network, --external) ──────────────────────
def check_external_links():
    findings = []
    ext_urls = set()
    for f in HTML_FILES:
        content = FILE_CLEAN[f]
        for m in ATTR_RE.finditer(content):
            target = m.group(2)
            if not target or "${" in target:
                continue
            if is_internal(target) == True:
                continue
            if is_internal(target) == "skip":
                continue
            ext_urls.add(target)
    ext_urls = sorted(ext_urls)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(check_url, u): u for u in ext_urls}
        for fut in concurrent.futures.as_completed(futs):
            u = futs[fut]
            try:
                results[u] = fut.result()
            except Exception as e:
                results[u] = (None, u, str(e), None)

    non200 = 0
    botblocked = 0
    for u in ext_urls:
        status, final_url, err, _ = results.get(u, (None, u, "not checked", None))
        if status == 200:
            continue
        if status in (403, 999):
            botblocked += 1
            findings.append(f"{u}: status {status} (bot-block, UNVERIFIED)")
        elif status is None:
            botblocked += 1
            findings.append(f"{u}: UNVERIFIED ({err})")
        else:
            non200 += 1
            findings.append(f"{u}: status {status}")
    findings.insert(0, f"{len(ext_urls)} unique external URLs checked; {non200} non-200, {botblocked} bot-blocked/unverified")
    add_section("13. External links (WARN, network)", False, findings)


# ── 14. Workflow health (WARN) ───────────────────────────────────────────
def check_workflow_health():
    findings = []
    has_token = bool(os.environ.get("GITHUB_TOKEN"))
    has_gh_auth = False
    if not has_token:
        try:
            r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=15)
            has_gh_auth = r.returncode == 0
        except Exception:
            has_gh_auth = False
    if not (has_token or has_gh_auth):
        add_section("14. Workflow health (WARN, skipped: no GITHUB_TOKEN or gh auth)", False, [])
        return
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--workflow", "refresh_state_capacity.yml", "--limit", "1",
             "--json", "conclusion,updatedAt"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            findings.append(f"gh run list failed: {r.stderr.strip()[:200]}")
        else:
            runs = json.loads(r.stdout or "[]")
            if not runs:
                findings.append("no runs found for 'Refresh State Capacity Data'")
            else:
                run = runs[0]
                conclusion = run.get("conclusion")
                updated = run.get("updatedAt")
                if conclusion != "success":
                    findings.append(f"last run concluded {conclusion!r} (expected success)")
                else:
                    updated_dt = datetime.datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ")
                    age_hours = (datetime.datetime.utcnow() - updated_dt).total_seconds() / 3600
                    if age_hours > 48:
                        findings.append(f"last successful run was {age_hours:.1f}h ago (updated {updated})")
    except Exception as e:
        findings.append(f"could not query workflow runs ({e})")
    add_section("14. Workflow health (WARN)", False, findings)


# ── main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--external", action="store_true", help="also run the external-link pass")
    args = parser.parse_args()

    check_internal_links()
    check_stubs()
    check_seo_head()
    check_sitemap()
    chrome_pages = check_ribbon_footer()
    check_stats(chrome_pages)
    check_event_dates()
    check_latest_band()
    check_data_contracts()
    check_tokenizer_sync()
    check_copy_rules()
    check_live_site()
    if args.external:
        check_external_links()
    check_workflow_health()

    lines = []
    lines.append(f"# Site health, {TODAY.isoformat()}")
    lines.append("")
    lines.append(f"{check_count} checks, {hard_fail_count} hard failures, {warn_count} warnings")
    lines.append("")
    for title, status, findings in report_sections:
        lines.append(f"## {title}")
        lines.append(f"**{status}**")
        if findings:
            for item in findings:
                lines.append(f"- {item}")
        else:
            lines.append("- No issues found.")
        lines.append("")

    report = "\n".join(lines).rstrip() + "\n"
    print(report)
    with open(os.path.join(ROOT, "site_health_report.md"), "w", encoding="utf-8") as fh:
        fh.write(report)

    sys.exit(1 if hard_fail_count > 0 else 0)


if __name__ == "__main__":
    main()
