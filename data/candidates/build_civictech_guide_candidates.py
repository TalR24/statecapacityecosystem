"""Build a candidates CSV for Henry's State Capacity Ecosystem directory from the
Civic Tech Field Guide export (CC BY 4.0, https://civictech.guide).

Columns: Henry's ten, in his order, plus two trailing review columns
(Source URL, Match notes). Funding Model and Funding Detail are left blank
because the guide has no funding fields. Focus is filled only when the text
says so; otherwise blank for Henry to set.
"""
import csv, json, re, sys
from collections import Counter
from urllib.parse import urlparse

import os, time, urllib.request, urllib.error
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EXPORT = os.path.join(HERE, "civictech_guide_export.json")       # cached raw export (gitignored)
DIRECTORY = os.path.join(ROOT, "data", "directory.csv")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, f"civictech_guide_candidates_{date.today().isoformat()}.csv")

def fetch_export():
    """Page /api/v1/projects/export until an empty page, backing off on 429."""
    out, off, lim = [], 0, 500
    while True:
        url = f"https://civictech.guide/api/v1/projects/export?limit={lim}&offset={off}"
        for attempt in range(8):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SCE directory research; statecapacityecosystem@gmail.com)"})
                d = json.load(urllib.request.urlopen(req, timeout=90)); break
            except urllib.error.HTTPError as e:
                if e.code == 429: time.sleep(15 * (attempt + 1)); continue
                raise
        else:
            raise SystemExit(f"gave up at offset {off}")
        items = d.get("data") or []
        if not items: break
        out.extend(items); off += lim; time.sleep(6)
    json.dump(out, open(EXPORT, "w"))
    print(f"fetched {len(out)} records into {EXPORT}")

if not os.path.exists(EXPORT):
    fetch_export()

# category name -> (segment or None, problem area, problem topic)
CROSSWALK = {
    # Govtech
    "Issue reporting": ("GovTech", "Service Delivery", "Service Design"),
    "Identity": ("GovTech", "Technology & Data", "Data Integration"),
    "Official digital identity systems": ("GovTech", "Technology & Data", "Data Integration"),
    "Legislation trackers": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Access to laws": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Election administration": ("GovTech", "Participatory Democracy", "Democracy Infrastructure"),
    "Civic tech legislation and policy": ("Advocacy", "Participatory Democracy", "Democracy Infrastructure"),
    "Tech or Digital Policy": ("Research", "Domains", "AI in Government"),
    "Service alerts": ("GovTech", "Service Delivery", "Service Design"),
    "Tools for Parliamentarians and Legislators": ("GovTech", "Procurement & Operations", "Operational Excellence"),
    "Public meetings": ("GovTech", "Participatory Democracy", "Civic Engagement"),
    "Parliamentary and congressional monitoring": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Communicating with the government": ("GovTech", "Service Delivery", "Service Design"),
    "Meeting finders": ("GovTech", "Participatory Democracy", "Civic Engagement"),
    # Build something / Learn to build / Build your own
    "Innovation teams and labs": ("Government", "Test & Learn", "Iterative Learning"),
    "Building inside government": ("Government", "Test & Learn", "Iterative Learning"),
    "Civic apps outfits": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "Accelerators": ("Ecosystems", "Test & Learn", "Scaling What Works"),
    "Incubators": ("Ecosystems", "Test & Learn", "Scaling What Works"),
    "Public Private Partnerships": ("Ecosystems", "Procurement & Operations", "Procurement Reform"),
    "Design": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "User research": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "User research groups": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "Civic hackathons": ("Community", "Talent & Hiring", "Expert Contribution"),
    "Building in the private sector": ("GovTech", "Technology & Data", "Shared Platforms"),
    "Supporting public sector from outside government": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "Civic and social impact companies": ("GovTech", "Technology & Data", "Shared Platforms"),
    "Civic teams at tech companies": ("GovTech", "Technology & Data", "Shared Platforms"),
    "Participation consultants": ("Digital Services & Consulting", "Participatory Democracy", "Civic Engagement"),
    "Playbooks and design principles": ("Capacity Building", "Service Delivery", "Service Design"),
    "Social impact design firms": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "Co-design": ("Digital Services & Consulting", "Service Delivery", "Service Design"),
    "Toolkits": ("Capacity Building", "Service Delivery", "Service Design"),
    # The People
    "Fellowships": ("Fellowships", "Talent & Hiring", "Talent Pipeline"),
    "Find a job or hire someone": ("Ecosystems", "Talent & Hiring", "Hiring Process"),
    "Funders & donors": ("Philanthropy", "Test & Learn", "Scaling What Works"),
    "Investors": ("Investor", "Test & Learn", "Scaling What Works"),
    "Research and policy centers": ("Research", "Test & Learn", "Evidence Use"),
    "Think tanks": ("Research", "Test & Learn", "Evidence Use"),
    "Peer-reviewed research": ("Research", "Test & Learn", "Evidence Use"),
    "Civil society research outfits": ("Research", "Test & Learn", "Evidence Use"),
    "Public Interest Tech": ("Research", "Talent & Hiring", "Talent Pipeline"),
    "Academic programs": ("Capacity Building", "Talent & Hiring", "Talent Pipeline"),
    "Degree programs": ("Capacity Building", "Talent & Hiring", "Talent Pipeline"),
    "Courses": ("Capacity Building", "Talent & Hiring", "Workforce Development"),
    "Upskilling": ("Capacity Building", "Talent & Hiring", "Workforce Development"),
    "Partner networks and coalitions": ("Ecosystems", "Test & Learn", "Scaling What Works"),
    "Peer networks": ("Community", "Participatory Democracy", "Civic Engagement"),
    "Hubs": ("Ecosystems", "Test & Learn", "Scaling What Works"),
    "Trade groups": ("Ecosystems", "Procurement & Operations", "Procurement Reform"),
    "Civic hacking meetups": ("Community", "Talent & Hiring", "Expert Contribution"),
    "Pro bono and volunteer": ("Community", "Talent & Hiring", "Expert Contribution"),
    "Evaluate impact": ("Research", "Test & Learn", "Outcomes Measurement"),
    # Civic data
    "Open government data": ("GovTech", "Technology & Data", "Data Integration"),
    "Open data publishing portals": ("GovTech", "Technology & Data", "Shared Platforms"),
    "Open data publishing platforms": ("GovTech", "Technology & Data", "Shared Platforms"),
    "Dashboards": ("GovTech", "Test & Learn", "Outcomes Measurement"),
    # Transparency
    "Procurement oversight": ("Advocacy", "Procurement & Operations", "Procurement Reform"),
    "Budget explorers": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Access to information": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Government transparency": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Watchdogging government": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    "Promise trackers": ("Advocacy", "Participatory Democracy", "Transparency & Accountability"),
    # Participation
    "Digital participation platforms": ("GovTech", "Participatory Democracy", "Civic Engagement"),
    "Participatory budgeting": ("Community", "Participatory Democracy", "Civic Engagement"),
    "Participatory budgeting programs": ("Government", "Participatory Democracy", "Civic Engagement"),
    "Participatory budgeting tools": ("GovTech", "Participatory Democracy", "Civic Engagement"),
    "Deliberation": ("Research", "Participatory Democracy", "Democracy Infrastructure"),
    "Sortition & Citizen Assemblies": ("Advocacy", "Participatory Democracy", "Democracy Infrastructure"),
    "Urban planning": ("GovTech", "Domains", "Housing & Land Use"),
    "Surveys & polling": ("GovTech", "Test & Learn", "Feedback Loops"),
    "Democratic Innovations": ("Research", "Participatory Democracy", "Democracy Infrastructure"),
    # AI and emerging
    "Governance of AI": ("Research", "Domains", "AI in Government"),
    "AI Auditing": ("Research", "Domains", "AI in Government"),
    "Testbeds and Sandboxes": ("Ecosystems", "Test & Learn", "Iterative Learning"),
    # Adjacent
    "Cybersecurity": ("GovTech", "Technology & Data", "Data Security"),
    "Connectivity": ("Advocacy", "Domains", "Broadband & Internet Connectivity"),
    "Disaster response and humanitarian tech": ("GovTech", "Domains", "Crisis Response"),
    "Preparedness": ("GovTech", "Domains", "Crisis Response"),
    "Digital Public Goods": ("Ecosystems", "Technology & Data", "Shared Platforms"),
}
# Categories that are government-facing by definition; everything else in the
# crosswalk counts only when the record's own text talks about government.
CORE = {"Issue reporting", "Identity", "Official digital identity systems", "Legislation trackers", "Access to laws",
    "Election administration", "Civic tech legislation and policy", "Tech or Digital Policy", "Service alerts",
    "Tools for Parliamentarians and Legislators", "Public meetings", "Parliamentary and congressional monitoring",
    "Communicating with the government", "Meeting finders", "Innovation teams and labs", "Building inside government",
    "Civic apps outfits", "Public Private Partnerships", "Supporting public sector from outside government",
    "Open government data", "Open data publishing portals", "Open data publishing platforms", "Procurement oversight",
    "Budget explorers", "Government transparency", "Watchdogging government", "Promise trackers",
    "Digital participation platforms", "Participatory budgeting programs", "Participatory budgeting tools",
    "Governance of AI", "AI Auditing", "Testbeds and Sandboxes", "Digital Public Goods"}
GOV_RE = re.compile(r"\b(government|governments|public sector|public servants|civil service|agency|agencies|municipal|municipalit|city hall|cities|counties|county|state and local|federal|congress|legislat|policymakers|public administration|public services?|civic tech(nology)? for government|govtech)\b", re.I)
ORGTYPE_SEGMENT = {
    "Government / public sector": "Government",
    "Academic / research organization": "Research",
    "Advocacy organization": "Advocacy",
    "Grassroots / Indie project": "Community",
}
ALLOWED_TYPES = {"Organization", "Program", "Network", "Working groups"}
SKIP_ORGTYPES = {"Media organization", "Multilateral institution"}

def norm_name(s):
    s = re.sub(r"\(.*?\)", "", s or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def domain(u):
    if not u: return ""
    if not re.match(r"^https?://", u): u = "https://" + u
    d = urlparse(u).netloc.lower()
    return d[4:] if d.startswith("www.") else d

def as_list(v):
    if v is None: return []
    if isinstance(v, list): return [str(x) for x in v]
    return [str(v)]

FED = re.compile(r"\b(federal|nationwide|national|U\.S\.|United States|Congress|GSA|OPM|USDS|White House|agencies across the country)\b", re.I)
STATE = re.compile(r"\b(state government|state agenc|statewide|state of [A-Z]|governor|legislature)\b", re.I)
CITY = re.compile(r"\b(city|cities|municipal|county|counties|local government|mayor)\b", re.I)

def focus_from(text):
    f = []
    if FED.search(text): f.append("Federal")
    if STATE.search(text): f.append("State")
    if CITY.search(text): f.append("City")
    return ", ".join(f)

def first_sentence(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    return m.group(1) if m else s

existing = list(csv.DictReader(open(DIRECTORY)))
ex_names = {norm_name(r["Org Name"]) for r in existing}
ex_domains = {domain(r["Website"]) for r in existing if r["Website"]}

records = json.load(open(EXPORT))
rows, reasons = [], Counter()
for r in records:
    raw = r.get("raw_data") or {}
    status = (r.get("status") or raw.get("Status") or "").lower()
    if status and status != "active": reasons["not active"] += 1; continue
    country = " ".join(as_list(raw.get("Country") or raw.get("HQ Country") or r.get("country") or r.get("location", {}).get("country") if isinstance(r.get("location"), dict) else r.get("country")))
    hq = " ".join(as_list(raw.get("HQ Location") or raw.get("Simple place name") or ""))
    if "United States" not in country and not re.search(r"\b(USA|U\.S\.|United States)\b", hq) and not re.search(r", (AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b", hq):
        reasons["not US"] += 1; continue
    ptypes = set(as_list(r.get("projectTypes") or raw.get("Project type") or raw.get("Type")))
    if not ptypes & ALLOWED_TYPES: reasons["not an org/program/network"] += 1; continue
    otypes = as_list(r.get("organizationType") or raw.get("Organization type"))
    if set(otypes) & SKIP_ORGTYPES: reasons["media or multilateral"] += 1; continue
    cats = as_list(r.get("categories"))
    matched = [c for c in cats if c in CROSSWALK]
    if not matched: reasons["no crosswalk category"] += 1; continue
    name = (r.get("title") or "").strip()
    text_all = " ".join([name, r.get("description") or "", str(r.get("longDescription") or ""), str(raw.get("1-liner") or "")])
    core_hit = any(c in CORE for c in matched)
    if not core_hit and not GOV_RE.search(text_all): reasons["supporting category, no government language"] += 1; continue
    tier = "core" if core_hit else "supporting"
    url = (r.get("url") or (r.get("socials") or {}).get("website") if isinstance(r.get("socials"), dict) else r.get("url")) or ""
    if norm_name(name) in ex_names or (domain(url) and domain(url) in ex_domains): reasons["already in directory"] += 1; continue
    desc = re.sub(r"\s+", " ", (r.get("description") or raw.get("1-liner") or "")).strip()
    longd = r.get("longDescription") or raw.get("Longer description") or ""
    if len(desc) < 60 and longd: desc = (desc + " " + first_sentence(longd)).strip()
    if not desc or not url: reasons["missing description or website"] += 1; continue
    segs = []
    for o in otypes:
        if o in ORGTYPE_SEGMENT: segs.append(ORGTYPE_SEGMENT[o])
    for c in matched:
        s = CROSSWALK[c][0]
        if s and s not in segs: segs.append(s)
    if not segs: reasons["no segment"] += 1; continue
    areas, topics = [], []
    for c in matched:
        a, t = CROSSWALK[c][1], CROSSWALK[c][2]
        if a not in areas: areas.append(a)
        if t not in topics: topics.append(t)
    rows.append({
        "Org Name": name,
        "Primary Segment": segs[0],
        "Secondary Segments": ",".join(segs[1:3]),
        "Focus": focus_from(name + " " + desc + " " + str(longd)[:600]),
        "Description": desc[:400],
        "Funding Model": "",
        "Funding Detail": "",
        "Website": url,
        "Problem Area": ",".join(areas[:3]),
        "Problem Topic": ",".join(topics[:3]),
        "Source URL": f"https://civictech.guide/{r.get('slug','')}" if r.get("slug") else "https://civictech.guide/",
        "Match notes": tier + ": " + "; ".join(matched[:4]) + (" | " + ", ".join(otypes) if otypes else ""),
        "_n": (10 if tier == "core" else 0) + len(matched),
    })
rows.sort(key=lambda x: (-x["_n"], x["Org Name"].lower()))
cols = ["Org Name", "Primary Segment", "Secondary Segments", "Focus", "Description", "Funding Model", "Funding Detail", "Website", "Problem Area", "Problem Topic", "Source URL", "Match notes"]
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
print("records in export:", len(records)); print("candidates:", len(rows)); print("excluded:", dict(reasons))
print("segments:", Counter(r["Primary Segment"] for r in rows).most_common())
print("focus filled:", sum(1 for r in rows if r["Focus"]), "of", len(rows))
