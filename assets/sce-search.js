/* SCESearch: shared ranked search over organizations (data/directory.json,
 * data/affinity_search.json) and people/opportunities (data/connect.json).
 * Used by the search modal (ecosystem/index.html, ecosystem/search/index.html)
 * and the Organization Directory search box (ecosystem/organizations/index.html).
 *
 * The tokenizer and org-ranking logic (STOPWORDS, SHORT_TERMS, GEO_FOCUS_MAP,
 * place alias groups, detectPlaceTerm, funding-intent boost) are copied
 * verbatim from ecosystem/affinity-map/index.html so all three surfaces rank
 * organizations the same way. Do not edit affinity-map's copy from here.
 */
(function (global) {
  "use strict";

  const DIR_URL    = "/data/directory.json";
  const CONNECT_URL = "/data/connect.json";
  const SEARCH_URL  = "/data/affinity_search.json";

  // ── Tokenizer (copied verbatim from ecosystem/affinity-map/index.html) ────
  const STOPWORDS = new Set("a an the and or but if then so of in on at to for from with by about into over through across under above between among against during before after up down out off as is are was were be been being have has had do does did doing this that these those there here it its their our your his her my we they them us i you he she who whom what which whose when where why how all any both each few more most other some such no nor not only own same than too very can will just dont don't".split(/\s+/));
  const SHORT_TERMS = new Set(["ai", "ml", "ux", "hr", "dc", "ev"]);
  function tokenize(s) {
    return (String(s || "").toLowerCase().match(/[a-z][a-z\-]+/g) || [])
      .filter(t => (t.length > 2 || SHORT_TERMS.has(t)) && !STOPWORDS.has(t));
  }
  const GEO_FOCUS_MAP = [
    { terms: ["nyc", "new york city", "new york", "city", "local", "municipal", "county"], focus: "City" },
    { terms: ["state", "albany", "statewide"], focus: "State" },
    { terms: ["federal", "national", "dc", "washington", "capitol"], focus: "Federal" },
  ];
  const FUND_INTENT_WORDS = ["fund", "funds", "funder", "funders", "funding", "foundation", "philanthropy", "investor", "invest"];
  const PLACE_ALIAS_GROUPS = [
    ["nyc", "new york city", "new york"],
    ["washington dc", "washington d.c.", "dc", "d.c."],
  ];
  const PLACE_ALIAS_MAP = (() => {
    const m = new Map();
    PLACE_ALIAS_GROUPS.forEach((group, i) => group.forEach(t => m.set(t, "group:" + i)));
    return m;
  })();
  function canonicalPlace(term) { return PLACE_ALIAS_MAP.get(term) || term; }
  function termMatches(lq, term) {
    const esc = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp("(^|[^a-z0-9])" + esc + "($|[^a-z0-9])", "i");
    return re.test(lq);
  }
  let geoTermUniverse = null;
  function buildGeoTermUniverse(orgs) {
    const terms = new Set();
    for (const o of orgs) (o.geo_terms || []).forEach(t => terms.add(String(t).toLowerCase()));
    GEO_FOCUS_MAP.forEach(g => g.terms.forEach(t => terms.add(t)));
    geoTermUniverse = [...terms].sort((a, b) => b.length - a.length);
  }
  function detectPlaceTerm(q) {
    const lq = q.toLowerCase();
    for (const t of geoTermUniverse) if (termMatches(lq, t)) return t;
    return null;
  }

  // ── Problem taxonomy (the Methodology page's areas → topics) ─────────────
  // Shared by the Problem filter menu (both search pages) and the tag boost
  // below; exposed as SCESearch.TAXONOMY so pages don't duplicate it.
  const TAXONOMY = {
    "Participatory Democracy": ["Civic Engagement", "Democracy Infrastructure", "Transparency & Accountability"],
    "Procurement & Operations": ["Operational Excellence", "Procurement Reform", "Reaction Time", "Regulatory & Administrative Burden"],
    "Service Delivery": ["Benefits Access", "Service Design"],
    "Talent & Hiring": ["Expert Contribution", "Hiring Architecture", "Hiring Process", "Talent Pipeline", "Workforce Development"],
    "Technology & Data": ["Data Integration", "Data Security", "Legacy Systems", "Shared Platforms"],
    "Test & Learn": ["Evidence Use", "Feedback Loops", "Iterative Learning", "Outcomes Measurement", "Scaling What Works"],
    "Domains": ["AI in Government", "Broadband & Internet Connectivity", "Child Welfare", "Criminal Justice", "Crisis Response", "Economic Mobility", "Education Delivery", "Healthcare Access", "Housing & Land Use", "Permitting & Licensing", "Physical Infrastructure", "Public Health", "Tax & Revenue"],
  };
  // Longest first so a query is checked against the most specific tag names first.
  const ALL_TAGS = (() => {
    const set = new Set();
    Object.keys(TAXONOMY).forEach(area => { set.add(area); TAXONOMY[area].forEach(t => set.add(t)); });
    return [...set].sort((a, b) => b.length - a.length);
  })();
  function detectTagMatches(lq) {
    return ALL_TAGS.filter(tag => lq.includes(tag.toLowerCase()));
  }

  // ── Module state ───────────────────────────────────────────────────────
  let _loaded = null;
  let _orgs = [], _people = [], _searchIdx = null;
  const _vocabIdx = new Map();
  let _orgTokenSets = [];
  let _peopleVectors = [];
  let _peopleTokenSets = [];

  function fallbackIdf() {
    const N = _orgs.length;
    return Math.log((1 + N) / 1) + 1;
  }

  function orgSearchText(o) {
    return [
      o.name, o.description, o.primary_segment,
      ...(o.segments || []), ...(o.problem_statements || []),
      ...(o.problem_areas || []), ...(o.focus || []),
    ].join(" ");
  }
  function personSearchText(p) {
    const offering = Array.isArray(p.offering) ? p.offering : [p.offering].filter(Boolean);
    return [
      p.name, p.organization, p.role, p.details,
      ...(p.problem_topics || []), ...(p.problem_areas || []),
      ...offering, ...(p.geography || []),
    ].join(" ");
  }

  function load() {
    if (_loaded) return _loaded;
    _loaded = Promise.all([
      fetch(DIR_URL).then(r => r.json()),
      fetch(CONNECT_URL).then(r => r.json()),
      fetch(SEARCH_URL).then(r => r.json()),
    ]).then(([orgs, people, idx]) => {
      _orgs = orgs; _people = people; _searchIdx = idx;
      idx.vocab.forEach((t, i) => _vocabIdx.set(t, i));
      buildGeoTermUniverse(_orgs);
      _orgTokenSets = _orgs.map(o => new Set(tokenize(orgSearchText(o))));

      _peopleTokenSets = _people.map(p => new Set(tokenize(personSearchText(p))));
      _peopleVectors = _people.map(p => {
        const toks = tokenize(personSearchText(p));
        const vec = {};
        toks.forEach(t => {
          const i = _vocabIdx.get(t);
          const key = i !== undefined ? "v" + i : "w:" + t;
          const w = i !== undefined ? _searchIdx.idf[i] : fallbackIdf();
          vec[key] = (vec[key] || 0) + w;
        });
        let norm = 0; for (const k in vec) norm += vec[k] * vec[k];
        norm = Math.sqrt(norm) || 1;
        for (const k in vec) vec[k] /= norm;
        return vec;
      });
      return true;
    });
    return _loaded;
  }

  function queryVectorOrg(qTokens) {
    const qv = {};
    qTokens.forEach(t => {
      const i = _vocabIdx.get(t);
      if (i === undefined) return;
      qv[i] = (qv[i] || 0) + _searchIdx.idf[i];
    });
    let norm = 0; for (const k in qv) norm += qv[k] * qv[k];
    norm = Math.sqrt(norm) || 1;
    for (const k in qv) qv[k] /= norm;
    return qv;
  }
  function queryVectorPeople(qTokens) {
    const qv = {};
    qTokens.forEach(t => {
      const i = _vocabIdx.get(t);
      const key = i !== undefined ? "v" + i : "w:" + t;
      const w = i !== undefined ? _searchIdx.idf[i] : fallbackIdf();
      qv[key] = (qv[key] || 0) + w;
    });
    let norm = 0; for (const k in qv) norm += qv[k] * qv[k];
    norm = Math.sqrt(norm) || 1;
    for (const k in qv) qv[k] /= norm;
    return qv;
  }
  function cosine(qv, ov) {
    let s = 0;
    for (const k in qv) s += qv[k] * (ov[k] || 0);
    return s;
  }
  function matchedTerms(qTokensUnique, tokenSet, limit) {
    const out = [];
    for (const t of qTokensUnique) {
      if (tokenSet.has(t)) { out.push(t); if (out.length >= limit) break; }
    }
    return out;
  }

  function problemSetsMatch(fieldA, fieldB, area, topic) {
    if (!area.size && !topic.size) return true;
    const combined = new Set([...area, ...topic]);
    return (fieldA || []).some(a => combined.has(a)) || (fieldB || []).some(t => combined.has(t));
  }

  function passesOrgFilters(o, f) {
    if (f.show === "people") return false;
    if (f.seg && f.seg.size && !f.seg.has(o.primary_segment)) return false;
    if (!problemSetsMatch(o.problem_areas, o.problem_statements, f.area || new Set(), f.topic || new Set())) return false;
    if (f.geo && f.geo.size && !(o.focus || []).some(x => f.geo.has(x))) return false;
    return true;
  }
  function passesPersonFilters(p, f) {
    if (f.show === "orgs") return false;
    if (!problemSetsMatch(p.problem_areas, p.problem_topics, f.area || new Set(), f.topic || new Set())) return false;
    if (f.geo && f.geo.size && !(p.geography || []).some(x => f.geo.has(x))) return false;
    return true;
  }

  function search(q, filters) {
    const f = Object.assign({ show: "both" }, filters || {});
    const rawQ = (q || "").trim();
    let orgsOut = [], peopleOut = [];

    if (!rawQ) {
      if (f.show !== "people") {
        _orgs.forEach(o => { if (passesOrgFilters(o, f)) orgsOut.push({ org: o, score: o.degree || 0, why: [] }); });
        orgsOut.sort((a, b) => b.score - a.score);
      }
      if (f.show !== "orgs") {
        _people.forEach(p => { if (passesPersonFilters(p, f)) peopleOut.push({ person: p, score: p.id, why: [] }); });
        peopleOut.sort((a, b) => b.score - a.score);
      }
      return { orgs: orgsOut, people: peopleOut, total: orgsOut.length + peopleOut.length };
    }

    const qTokens = tokenize(rawQ);
    const qTokensUnique = [...new Set(qTokens)];
    const lq = rawQ.toLowerCase();
    const place = detectPlaceTerm(rawQ);
    const placeCanon = place ? canonicalPlace(place) : null;
    const levelEntry = place ? GEO_FOCUS_MAP.find(g => g.terms.includes(place)) : null;
    const hasFundIntent = FUND_INTENT_WORDS.some(w => termMatches(lq, w));
    const queryTagMatches = detectTagMatches(lq);

    if (f.show !== "people") {
      const qv = queryVectorOrg(qTokens);
      _orgs.forEach((o, idx) => {
        if (!passesOrgFilters(o, f)) return;
        const ov = _searchIdx.vectors[idx];
        let s = cosine(qv, ov);
        const nameHit = o.name.toLowerCase().includes(lq);
        if (nameHit) s += 0.5;
        let geoHit = false, levelHit = false, fundHit = false;
        if (place) {
          const rawGeo = o.geo_terms || [];
          const geoCanon = rawGeo.map(x => canonicalPlace(String(x).toLowerCase()));
          if (geoCanon.includes(placeCanon)) { s *= 1.5; geoHit = true; }
          else if (rawGeo.length === 0 && levelEntry && (o.focus || []).includes(levelEntry.focus)) { s *= 1.25; levelHit = true; }
        }
        if (hasFundIntent && (o.primary_segment === "Philanthropy" || o.primary_segment === "Investor")) { s *= 1.5; fundHit = true; }
        const orgTags = queryTagMatches.filter(t => (o.problem_statements || []).includes(t) || (o.problem_areas || []).includes(t));
        if (orgTags.length) { s = (s || 0.02) * Math.pow(1.75, orgTags.length); }
        if (s <= 0.01 && !nameHit) return;
        const why = matchedTerms(qTokensUnique, _orgTokenSets[idx], 4);
        if (nameHit) why.push("name");
        if (geoHit) why.push("place: " + place);
        else if (levelHit) why.push("level: " + { City: "local", State: "state", Federal: "federal" }[levelEntry.focus]);
        if (fundHit) why.push("funding");
        orgTags.forEach(t => why.push("tag: " + t));
        orgsOut.push({ org: o, score: s, why });
      });
    }
    if (f.show !== "orgs") {
      const qv = queryVectorPeople(qTokens);
      _people.forEach((p, idx) => {
        if (!passesPersonFilters(p, f)) return;
        const pv = _peopleVectors[idx];
        let s = cosine(qv, pv);
        const nameHit = (p.name || "").toLowerCase().includes(lq);
        const orgHit = (p.organization || "").toLowerCase().includes(lq);
        if (nameHit) s += 0.5;
        if (orgHit) s += 0.25;
        const personTags = queryTagMatches.filter(t => (p.problem_topics || []).includes(t) || (p.problem_areas || []).includes(t));
        if (personTags.length) { s = (s || 0.02) * Math.pow(1.75, personTags.length); }
        if (s <= 0.01 && !nameHit && !orgHit) return;
        const why = matchedTerms(qTokensUnique, _peopleTokenSets[idx], 4);
        if (nameHit) why.push("name");
        personTags.forEach(t => why.push("tag: " + t));
        peopleOut.push({ person: p, score: s, why });
      });
    }
    orgsOut.sort((a, b) => b.score - a.score);
    peopleOut.sort((a, b) => b.score - a.score);
    return { orgs: orgsOut, people: peopleOut, total: orgsOut.length + peopleOut.length };
  }

  function nearestTopics(q, n) {
    n = n || 2;
    const qTokenSet = new Set(tokenize(q || ""));
    if (qTokenSet.size === 0) return [];
    const topics = [...new Set(_orgs.flatMap(o => o.problem_statements || []))];
    const scored = topics.map(t => {
      let s = 0;
      tokenize(t).forEach(tok => {
        if (qTokenSet.has(tok)) {
          const i = _vocabIdx.get(tok);
          s += i !== undefined ? _searchIdx.idf[i] : fallbackIdf();
        }
      });
      return { t, s };
    }).filter(x => x.s > 0);
    scored.sort((a, b) => b.s - a.s);
    return scored.slice(0, n).map(x => x.t);
  }

  // A Connect entry reads as an "Opportunity" card (vs. a "Person" card) when
  // it offers a grant/challenge or a job/fellowship AND its name looks like a
  // program name rather than a person's name (a digit, or one of these words).
  const OPPORTUNITY_NAME_WORDS = ["program", "programme", "fellowship", "fellows", "fund", "initiative", "network", "project", "lab", "center", "centre", "office", "digital", "service", "corps", "alliance", "institute", "foundation", "association", "council", "coalition", "summit", "week", "rfp", "rfei", "call", "challenge", "grant", "deployment", "partnership", "talent", "hub", "academy", "series"];
  function isOpportunity(p) {
    const offs = Array.isArray(p.offering) ? p.offering : [p.offering].filter(Boolean);
    if (!offs.includes("Grant / Challenge") && !offs.includes("Job / Fellowship")) return false;
    const name = (p.name || "").toLowerCase();
    if (/\d/.test(name)) return true;
    return OPPORTUNITY_NAME_WORDS.some(w => name.includes(w));
  }

  global.SCESearch = { load, search, nearestTopics, TAXONOMY, isOpportunity };
})(window);
