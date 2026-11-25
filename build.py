#!/usr/bin/env python3
"""Build the tldrcve static site from content/*.json. Standard library only.

    python3 build.py            # writes site/
    python3 build.py --strict   # same, but fails on any warning (use in CI)
    python3 build.py --public   # launch build: lets search engines index the site
"""
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
OUT = ROOT / "site"
VERSIONS_DIR = ROOT / "versions"
WATCH_DIR = ROOT / "watch"
SITE_URL = "https://tldrcve.com"

VERDICTS = {"now": "Patch now", "if": "Patch now if…", "cycle": "Next cycle", "watch": "Watching"}
# Status wording, shared by the page's status list and the feeds' categories: (state, text); state: yes | part | no
EXPLOIT_LABELS = {"public": ("yes", "Public exploit code is out"), "demonstrated": ("part", "Shown working, code not public"),
                  "none": ("no", "No public exploit")}
ATTACK_LABELS = {"seen": ("yes", "Attacks seen in the wild"), "none": ("no", "No attacks seen yet")}

# Page kinds. A vulnerability page asks "am I exposed, what do I patch?"; an incident page asks "was I hit, what do I
# clean up?" for something that already happened to someone (a vendor-side compromise, a breach).
KINDS = ("vulnerability", "incident")
# What sets an incident's place on the meter. Each page gives a state (yes, part, no) and a cite for every check.
INCIDENT_CHECKS = [
    ("confirmed", {"yes": "Confirmed on the record", "part": "Confirmed only by unnamed sources", "no": "Not confirmed"}),
    ("taken", {"yes": "Data, money or secrets taken", "part": "Data exposed; what was taken is unclear", "no": "Nothing reported taken"}),
    ("reach", {"yes": "Reached other organisations or the public", "part": "May have reached others", "no": "Limited to one organisation"}),
    ("entry", {"yes": "How they got in is known", "part": "Entry point named, details missing", "no": "How they got in is unknown"}),
    ("contained", {"yes": "Attackers shut out", "part": "Partly contained", "no": "Not contained"}),
]
ENTRY_TAGS = {"yes": "Entry point known", "part": "Entry point named", "no": "Entry point unknown"}
INCIDENT_CHECK_HELP = {
    "confirmed": "A named person, the victim, the vendor or an official body says it happened. Partly: only unnamed sources.",
    "taken": "A source says data, money or secrets were taken, not just exposed. Partly: exposed, but what was taken is unclear.",
    "reach": "It reached other organisations, their customers or the public. Partly: sources say others may be hit.",
    "entry": "How the attackers got in is known. Partly: a flaw or route is named, but not explained.",
    "contained": "The way in is closed and the attackers are out. Partly: closed, but stolen secrets still work or sources disagree.",
}
WHO_HELP = {
    "record": "A named person or organisation said it publicly.",
    "official": "An official spoke for an agency or company, without a name.",
    "anonymous": "A reporter's unnamed source.",
    "press": "Only the news report says it.",
}
ROOT_CAUSE_HELP = {
    "vendor-flaw": "A bug in a provider's own service, which only the provider could fix.",
    "supply-chain": "Victims got the attack through a trusted third party's code or service.",
    "known-bug": "A bug that already had a patch, left unpatched.",
    "zero-day": "A bug attacked before any patch existed.",
    "stolen-login": "A stolen, guessed or reused password, key or token.",
    "misconfig": "A setting that left the door open.",
    "unknown": "Nobody has said yet.",
}
ROOT_CAUSES = {
    "vendor-flaw": "Flaw in the provider's own service",
    "supply-chain": "Supply chain: a trusted third party served it",
    "known-bug": "Known bug, patch was available",
    "zero-day": "Zero-day: no patch existed",
    "stolen-login": "Stolen or guessed login",
    "misconfig": "Misconfiguration",
    "unknown": "Not disclosed yet",
}
WHO_LABELS = {"record": "On the record", "official": "Unnamed official", "anonymous": "Anonymous source",
              "press": "Press report"}

# Scare-o-meter zones, 0–4.
ZONES = [
    (1, "Shrug", "Real, but not worth losing sleep over."),
    (2, "Keep an eye on it", "Patch on schedule. Watch for news."),
    (3, "Check today", "Find out if you're affected. If you are, patch."),
    (4.01, "Drop everything", "Attackers are already on it. Patch now."),
]
# Incident pages use the same meter, read as "how bad is it?" instead of "how fast should I patch?".
INCIDENT_ZONES = [
    (1, "Minor", "Contained, little or nothing taken."),
    (2, "Notable", "One organisation hit. Limited data, or still unconfirmed."),
    (3, "Serious", "Sensitive data exposed, others may be hit, or still unexplained."),
    (4.01, "Severe", "Wide reach, money or secrets taken, or still open."),
]
METER_COLORS = ["var(--m1)", "var(--m2)", "var(--m3)", "var(--m4)"]

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '  <link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@500..900'
    "&family=Instrument+Sans:wght@400..700&family=IBM+Plex+Mono:wght@400;500;600"
    '&display=swap" rel="stylesheet">'
)

ICONS = {
    "copy": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>',
    "link": '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/></svg>',
    "x": '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M17.8 3h3.1l-6.8 7.7L22 21h-6.2l-4.9-6.4L5.3 21H2.2l7.3-8.3L2 3h6.4l4.4 5.8L17.8 3Zm-1.1 16.2h1.7L7.4 4.7H5.6l11.1 14.5Z"/></svg>',
    "in": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5ZM3 9.5h4V21H3V9.5Zm6.5 0h3.8v1.6h.1c.5-1 1.8-2 3.8-2 4 0 4.8 2.6 4.8 6V21h-4v-5.2c0-1.2 0-2.9-1.8-2.9s-2 1.4-2 2.8V21h-4V9.5Z"/></svg>',
    "back": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>',
}


def text(s: str) -> str:
    """Escape, then turn `backticks` into <code> and [label](/internal/path/) into a link (site paths only)."""
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(s, quote=False))
    return re.sub(r"\[([^\]]+)\]\((/[a-z0-9/-]*)\)", r'<a href="\2">\1</a>', out)


def plain(s: str) -> str:
    """Text for places without HTML (meta descriptions, the RSS feed): drop `backticks`, keep a link's label only."""
    return re.sub(r"\[([^\]]+)\]\((/[a-z0-9/-]*)\)", r"\1", s.replace("`", ""))


def og_image(path: str) -> tuple:
    """The link-preview image for a page path: (url, bytes). Falls back to the site default."""
    card = (path or "/").strip("/") or "default"
    if not (ASSETS / "og" / f"{card}.png").exists():
        card = "default"
    name = f"og/{card}.png"
    return f"{SITE_URL}/assets/{name}?v={asset_version(name)}", (ASSETS / name).stat().st_size


def nice_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def zone(scare: float, zones: list = None):
    zones = zones or ZONES
    for limit, label, hint in zones:
        if scare < limit:
            return label, hint
    return zones[-1][1], zones[-1][2]


def zone_for(c: dict):
    """The meter's label for a page: patch urgency, or for incidents how bad it is."""
    return zone(c["status"]["scare"], INCIDENT_ZONES if c.get("kind") == "incident" else ZONES)


def product_full(c: dict) -> str:
    """'Brotli (Node.js, .NET, Envoy, Python)': for the brief page."""
    extra = c.get("also_in", [])
    return f'{c["product"]} ({", ".join(extra)})' if extra else c["product"]


def product_short(c: dict) -> str:
    """'Brotli (Node.js +3 more)': short enough for a card or list row."""
    extra = c.get("also_in", [])
    if not extra:
        return c["product"]
    if len(extra) == 1:
        return f'{c["product"]} ({extra[0]})'
    return f'{c["product"]} ({extra[0]} +{len(extra) - 1} more)'


def asset_version(name: str) -> str:
    """Short content hash, so browsers fetch a new file whenever it changes."""
    return hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()[:10]


def fingerprinted(name: str) -> str:
    """/assets/v/site.<hash>.css: a new file name for every change, so a half-finished deploy can never
    serve the old file under the new URL (Cloudflare ignores ?v= when it picks the file)."""
    stem, ext = name.rsplit(".", 1)
    return f"/assets/v/{stem}.{asset_version(name)}.{ext}"


def write_fingerprinted() -> None:
    (OUT / "assets" / "v").mkdir(parents=True, exist_ok=True)
    for name in ("site.css", "site.js"):
        shutil.copyfile(ASSETS / name, OUT / fingerprinted(name).lstrip("/"))


def page(title: str, description: str, body: str, current: str = "", path: str = "", data: str = "") -> str:
    description = plain(description)
    seo = social_tags(title, description, path)
    data_link = f'\n  <link rel="alternate" type="application/json" title="This page as JSON" href="{data}">' if data else ""
    cur = {k: ' aria-current="page"' if k == current else "" for k in ("cves", "incidents", "versions", "week", "how")}
    return f"""<!doctype html>
<html lang="en" class="no-js">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
{seo}
  {FONTS}
  <link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">
  <link rel="icon" href="/assets/icons/icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/assets/icons/apple-touch-icon.png">
{FEED_LINKS}{data_link}
  <link rel="stylesheet" href="{fingerprinted("site.css")}">
  <script src="{fingerprinted("site.js")}" defer></script>
{ANALYTICS}
</head>
<body>
  <header class="site-header">
    <div class="wrap">
      <a class="wordmark" href="/" aria-label="tldrcve home"><span class="wordmark__tldr">tl;dr</span><span class="wordmark__cve">CVE</span></a>
      <nav class="site-nav" aria-label="Main">
        <a href="/cves/"{cur["cves"]}>All CVEs</a>
        <a href="/incidents/"{cur["incidents"]}>Incidents</a>
        <a href="/versions/"{cur["versions"]}>Safe versions</a>
        <a href="/week/"{cur["week"]}>Weekly</a>
        <a href="/how-we-rate/"{cur["how"]}>How we rate</a>
      </nav>
    </div>
  </header>
{body}
  <footer class="site-footer">
    <div class="wrap">
      <p class="follow">Follow <a href="https://x.com/{X_HANDLE}">@{X_HANDLE}</a> on X for live updates, or subscribe by RSS: <a href="/feed.xml">CVEs</a>, <a href="/incidents/feed.xml">incidents</a> or <a href="/all/feed.xml">both</a>.</p>
      <p>Every claim is sourced. Wrong or out of date? <a href="{REPO_URL}">Fix it on GitHub</a> or tell us on X. Made by <a href="https://x.com/{AUTHOR_HANDLE}">@{AUTHOR_HANDLE}</a>.</p>
    </div>
  </footer>
</body>
</html>
"""


# ---------- Scare-o-meter ----------

def _xy(r: float, deg: float):
    a = math.radians(deg)
    return 100 + r * math.cos(a), 100 - r * math.sin(a)


def gauge(scare: float, zones: list = None) -> str:
    r = 78
    arcs = []
    for i, color in enumerate(METER_COLORS):
        x0, y0 = _xy(r, 180 - 45 * i - 1.5)
        x1, y1 = _xy(r, 180 - 45 * (i + 1) + 1.5)
        arcs.append(f'<path d="M {x0:.2f} {y0:.2f} A {r} {r} 0 0 1 {x1:.2f} {y1:.2f}" stroke="{color}"/>')
    nx, ny = _xy(64, 180 - 45 * max(0.0, min(4.0, scare)))
    label, hint = zone(scare, zones)
    return f"""<div class="meter">
          <svg class="meter__svg" viewBox="0 0 200 112" role="img" aria-label="Scare-o-meter: {label}">
            <g fill="none" stroke-width="20">{"".join(arcs)}</g>
            <line x1="100" y1="100" x2="{nx:.2f}" y2="{ny:.2f}" class="meter__needle"/>
            <circle cx="100" cy="100" r="9" class="meter__hub"/>
          </svg>
          <p class="meter__name">Scare-o-meter</p>
          <p class="meter__label">{label}</p>
          <p class="meter__hint">{html.escape(hint).replace(". ", ".<br>")}</p>
        </div>"""


def mini_meter(scare: float) -> str:
    # Same zones as the big gauge, so the tile and the page always agree.
    filled = next((i + 1 for i, (limit, _, _) in enumerate(ZONES) if scare < limit), len(ZONES))
    segs = "".join(f'<span class="{"on" if i < filled else ""}"></span>' for i in range(4))
    label, _ = zone(scare)
    return f'<span class="mini-meter" data-level="{filled}" role="img" aria-label="Scare-o-meter: {label}">{segs}</span>'


# ---------- Brief page ----------

def checklist(c: dict) -> str:
    s = c["status"]
    rows = []  # (key, state, text); state: yes | part | no
    if c.get("kind") == "incident":
        checks = c["incident"]["checks"]
        cites = {k: v.get("cite", []) for k, v in checks.items()}
        for key, words in INCIDENT_CHECKS:
            st = checks[key]["state"]
            rows.append((key, st, words[st]))
        kev = s.get("kev")
        if kev:
            rows.append(("kev", "yes", f"Its bug is on CISA's exploited list (since {nice_date(kev['added'])})"))
            cites["kev"] = c.get("status_cite", {}).get("kev", [])
        return checklist_html(rows, cites)

    if "no_login" in s:
        rows.append(("no_login",) + (("yes", "Works without logging in") if s["no_login"]
                    else ("no", f"Needs {s.get('needs', 'a login')} first")))
    rows.append(("exploit",) + EXPLOIT_LABELS[s["exploit"]])
    rows.append(("attacks",) + ATTACK_LABELS[s["attacks"]])
    kev = s.get("kev")
    if kev:
        due = date.fromisoformat(kev["due"])
        when = f"fix by {nice_date(kev['due'])}" if due >= date.today() else f"since {nice_date(kev['added'])}"
        rows.append(("kev", "yes", f"On CISA's exploited list ({when})"))
    elif s.get("cisa_alert"):
        rows.append(("kev", "part", "CISA says patch now (not on its exploited list)"))
    else:
        rows.append(("kev", "no", "Not on CISA's exploited list"))

    return checklist_html(rows, c.get("status_cite", {}))


def checklist_html(rows: list, cites: dict) -> str:
    marks = {"yes": "✓", "part": "~", "no": ""}
    words = {"yes": "Yes", "part": "Partly", "no": "No"}
    items = "\n".join(
        f'          <li class="check check--{st}"><span class="check__box" aria-hidden="true">{marks[st]}</span>'
        f'<span class="visually-hidden">{words[st]}: </span><span>{html.escape(t)}{cite_marks({"cite": cites.get(k, [])})}</span></li>'
        for k, st, t in rows
    )
    return f'<ul class="checklist">\n{items}\n        </ul>'


def cite_marks(e: dict) -> str:
    if not e.get("cite"):
        return ""
    nums = ",".join(str(n) for n in e["cite"])
    return f'<sup class="cite"><a href="#sources">{nums}</a></sup>'


def pending_badge(pending: dict) -> str:
    """Something we're waiting on (a release, an advisory). Absolute dates only, never 'today'."""
    exp = pending.get("expected")
    if not exp:
        return '<span class="pending">Pending</span>'
    late = date.fromisoformat(exp) < date.today()
    word = "was due" if late else "expected"
    return f'<span class="pending{" pending--late" if late else ""}">Pending · {word} {nice_date(exp)}</span>'


def cve_list(c: dict) -> str:
    """CVE IDs for headings and meta lines. A release roundup can hold dozens, so show a count instead."""
    ids = c["cves"]
    if c.get("bugs"):  # count every bug in the release, including ones with their own page
        n = len(c["bugs"])  # say "CVEs" only when every bug has a CVE ID; otherwise "advisories"
        return f"{n} CVEs" if all(b["cve"].startswith("CVE-") for b in c["bugs"]) else f"{n} advisories"
    return ", ".join(ids) if len(ids) <= 3 else f"{len(ids)} CVEs"


def cve_paren(c: dict) -> str:
    """" (CVE-…)" after a page name, or nothing when no CVE is assigned yet (no empty brackets)."""
    ids = cve_list(c)
    return f" ({ids})" if ids else ""


def is_incident(c: dict) -> bool:
    return c.get("kind") == "incident"


def badge(c: dict, lg: bool = False) -> str:
    """The verdict badge, or "Incident" plus its entry-point status for incident pages."""
    size = " verdict--lg" if lg else ""
    if is_incident(c):
        entry = c.get("incident", {}).get("checks", {}).get("entry", {}).get("state")
        tag = entry_tag(entry) if entry and lg else ""
        return f'<span class="verdict verdict--incident{size}">Incident</span>{tag}'
    return f'<span class="verdict verdict--{c["verdict"]}{size}">{VERDICTS[c["verdict"]]}</span>'


def badge_text(c: dict) -> str:
    return "Incident" if is_incident(c) else VERDICTS[c["verdict"]]


def timeline_pane(c: dict) -> str:
    """Incidents: what's confirmed so far, each line dated and labelled by who says it."""
    items = c.get("timeline") or []
    if not items:
        return ""
    rows = "\n".join(
        f'        <li><time datetime="{e["date"]}">{nice_date(e["date"])}</time><span>'
        f'<span class="who who--{e["who"]}">{WHO_LABELS[e["who"]]}</span> {text(e["text"])}{cite_marks(e)}</span></li>'
        for e in items)
    return f"""    <section class="pane" aria-labelledby="h-timeline">
      <div class="pane__head"><h2 id="h-timeline">What's confirmed</h2></div>
      <div class="pane__body"><ul class="changes timeline">
{rows}
      </ul></div>
    </section>
"""


def root_cause_pane(c: dict) -> str:
    rc = c.get("root_cause")
    if not rc:
        return ""
    chips = "".join(f'<span class="tag tag--soft">{ROOT_CAUSES[t]}</span>' for t in rc["tags"])
    body = f'<p>{text(rc["text"])}{cite_marks(rc)}</p>' if rc.get("text") else ""
    return f"""    <section class="pane" aria-labelledby="h-root">
      <div class="pane__head"><h2 id="h-root">Root cause</h2></div>
      <div class="pane__body"><p class="chips">{chips}</p>{body}</div>
    </section>
"""


SEVERITY_ORDER = ("critical", "high", "medium", "low")
ROUNDUP_OF = {}  # bug page slug -> the release roundup that lists it; filled in main()
PAGES = {}  # slug -> page; filled in main()
ROUNDUP_TAG = '<span class="tag">Roundup</span>'


def roundup_tag(c: dict) -> str:
    return ROUNDUP_TAG if c.get("bugs") else ""


def bug_list(c: dict) -> str:
    """A release roundup's bugs: critical and high ones as folds with who's affected, the rest as a compact list."""
    bugs = c.get("bugs", [])
    if not bugs:
        return ""
    def sev(b):
        return f'<span class="sev sev--{b["severity"]}">{b["severity"].title()}</span>'
    def advisory(b):
        return f'<a href="{html.escape(b["url"])}">{html.escape(b["cve"])}</a>'
    major = [b for b in bugs if b.get("text")]
    minor = [b for b in bugs if not b.get("text")]
    folds = []
    for b in major:
        verdict = f'<span class="verdict verdict--{b["verdict"]}">{VERDICTS[b["verdict"]]}</span>' if b.get("verdict") else ""
        own = f'<a class="bug__page" href="/{b["page"]}/">Full page →</a>' if b.get("page") else ""
        folds.append(f"""      <details class="fold bug{" bug--own" if own else ""}">
        <summary>{sev(b)}<span class="fold__title"><span class="bug__proj">{html.escape(b["project"])}</span> {text(b["title"])}</span>{own}{verdict}</summary>
        <div class="fold__body"><p>{text(b["text"])}</p><p class="bug__links">{advisory(b)}</p></div>
      </details>""")
    rest = ""
    if minor:
        counts = {k: sum(1 for b in minor if b["severity"] == k) for k in SEVERITY_ORDER}
        label = " and ".join(f"{n} {k}" for k, n in counts.items() if n)
        items = "\n".join(f'          <li>{sev(b)}<span class="bug__proj">{html.escape(b["project"])}</span>{advisory(b)}</li>' for b in minor)
        rest = f"""      <details class="fold bug">
        <summary><span class="fold__title">{label.capitalize()}: opt-in features or low impact</span></summary>
        <div class="fold__body"><ul class="bug-mini">
{items}
        </ul></div>
      </details>"""
    return f"""    <section class="pane" aria-labelledby="h-bugs" data-folds>
      <div class="pane__head">
        <h2 id="h-bugs">The bugs <span class="pane__sub">{len(bugs)} advisories</span></h2>
        <button class="link-btn" type="button" data-expand-all>Expand all</button>
      </div>
{chr(10).join(folds)}
{rest}
    </section>
"""


def fold_items(entries: list) -> str:
    out = []
    for i, e in enumerate(entries, 1):
        body = f"<p>{text(e['text'])}{cite_marks(e)}</p>" if e.get("text") else ""
        cmd = f"<pre><code>{html.escape(e['cmd'])}</code></pre>" if e.get("cmd") else ""
        if e.get("versions"):
            cmd += versions_embed(e["versions"])
        hint = '<span class="fold__hint">command</span>' if e.get("cmd") else ""
        if e.get("pending"):
            hint = pending_badge(e["pending"]) + hint
        out.append(
            f"""      <details class="fold">
        <summary><span class="fold__num">{i}</span><span class="fold__title">{text(e["label"])}</span>{hint}</summary>
        <div class="fold__body">{body}{cmd}</div>
      </details>"""
        )
    return "\n".join(out)


def versions_embed(pids: list) -> str:
    """Latest safe versions for each product, from versions/<id>.json, shown compactly inside an upgrade step."""
    checked = min(VERSIONS[pid]["checked"] for pid in pids)
    rows = []
    for pid in pids:
        v = VERSIONS[pid]
        chips = "".join(f'<span class="vchip"><span>{text(l["line"])}</span><b>{html.escape(l["latest"])}</b></span>' for l in v["lines"])
        older = f'<span class="safe__note">{text(v["older"])}</span>' if v.get("older") else ""
        rows.append(f'''        <div class="safe__prod">
          <a class="safe__name" href="/versions/{pid}/">{html.escape(v["name"])} →</a>
          <span class="vchips">{chips}</span>{older}
        </div>''')
    return f"""      <div class="safe">
        <p class="safe__title">Latest safe versions <span class="safe__when">checked {nice_date(checked)}</span></p>
{chr(10).join(rows)}
      </div>"""


def toolbar(c: dict) -> str:
    url = f"{SITE_URL}/{c['slug']}/"
    post = quote(f"{c['name']}{cve_paren(c)}: {VERDICTS[c['verdict']]}. Are you affected?")
    x = f"https://x.com/intent/post?text={post}&url={quote(url, safe='')}"
    li = f"https://www.linkedin.com/sharing/share-offsite/?url={quote(url, safe='')}"
    return f"""    <div class="toolbar">
      <a class="back" href="{"/incidents/" if is_incident(c) else "/cves/"}">{ICONS["back"]}{"Incidents" if is_incident(c) else "All CVEs"}</a>
      <div class="share" role="group" aria-label="Share">
        <button class="icon-btn" type="button" data-copy="tldr-text" aria-label="Copy TL;DR and link" data-tip="Copy TL;DR">{ICONS["copy"]}</button>
        <button class="icon-btn" type="button" data-copy-link="{html.escape(url)}" aria-label="Copy link" data-tip="Copy link">{ICONS["link"]}</button>
        <a class="icon-btn" href="{html.escape(x)}" target="_blank" rel="noopener" aria-label="Post on X" data-tip="Post on X">{ICONS["x"]}</a>
        <a class="icon-btn" href="{html.escape(li)}" target="_blank" rel="noopener" aria-label="Share on LinkedIn" data-tip="LinkedIn">{ICONS["in"]}</a>
      </div>
      <p id="tldr-text" class="visually-hidden">{html.escape(plain(c["tldr"]))} {html.escape(url)}</p>
    </div>"""


def part_of(c: dict) -> str:
    r = ROUNDUP_OF.get(c["slug"])
    if not r:
        return ""
    return (f'\n      <p class="part-of">Part of the <a href="/{r["slug"]}/">{html.escape(r["name"])} roundup</a>: '
            f'<a href="/{r["slug"]}/#h-bugs">see all {len(r["bugs"])} advisories →</a></p>')


# The TL;DR is the page in one or two sentences, and the X post is built from it, so it must fit a post with the link
# (280 characters, the link counts as 23, plus a line break).
TLDR_MAX = 256


def tldr_pane(c: dict) -> str:
    """TL;DR panel: the "tldr" answer, with the "summary" (what the TL;DR leaves out) under "More details"."""
    body = (f'        <p class="tldr__text">{text(c["tldr"])}</p>\n'
            f'        <details class="tldr__more"><summary>More details</summary><p>{text(c["summary"])}</p></details>')
    return f"""    <section class="pane tldr" aria-labelledby="h-tldr">
      <div class="pane__head"><h2 id="h-tldr">TL;DR</h2></div>
      <div class="pane__body">
{body}
      </div>
    </section>
"""


def brief(c: dict) -> str:
    v = c["verdict"]
    s = c["status"]
    kicker = [product_full(c), *(c["cves"] if len(c["cves"]) <= 3 and not c.get("bugs") else ["Release roundup", cve_list(c)])]
    if s.get("aka"):
        kicker.append(f"aka {s['aka']}")
    sources = "\n".join(
        f'        <li><a href="{html.escape(src["url"])}">{text(src["title"])}</a>'
        + (f' <span class="src-date">{html.escape(src["date"])}</span>' if src.get("date") else "")
        + "</li>"
        for src in c["sources"]
    )
    changes = "\n".join(
        f'        <li><time datetime="{ch["date"]}">{nice_date(ch["date"])}</time><span>{text(ch["text"])}</span></li>'
        for ch in c["changes"]
    )
    inc = is_incident(c)
    kick = html.escape(" · ".join(kicker))
    if c.get("orgs"):  # who it is about, spelled out and linked
        orgs = " and ".join(f'<a href="{html.escape(o["url"])}">{html.escape(o["name"])}</a>' for o in c["orgs"])
        kick = orgs + (" · " + html.escape(" · ".join(kicker[1:])) if kicker[1:] else "")
    affected = "" if not c.get("affected") else f"""    <section class="pane" aria-labelledby="h-affected" data-folds>
      <div class="pane__head">
        <h2 id="h-affected">{"Were you hit?" if inc else "Are you affected?"} <span class="pane__sub">only if <strong>all</strong> are true</span></h2>
        <button class="link-btn" type="button" data-expand-all>Expand all</button>
      </div>
{fold_items(c["affected"])}
    </section>

"""
    related = ""
    if c.get("related"):
        links = ", ".join(f'<a href="/{r}/">{html.escape(PAGES[r]["name"])}</a>' for r in c["related"])
        related = f'\n      <p class="related">Related on tldrcve: {links}</p>'
    body = f"""  <main class="wrap brief">
{toolbar(c)}

    <header class="brief-head">
      <p class="kicker">{kick}</p>
      <h1>{html.escape(c["name"])}</h1>
      <p class="verdict-line">{badge(c, lg=True)}{roundup_tag(c)}<span>{text(c["tile_line"])}</span></p>
{part_of(c)}
    </header>

{tldr_pane(c)}

    <section class="pane" aria-labelledby="h-scare">
      <div class="pane__head"><h2 id="h-scare">{"How bad is it?" if inc else "How scary is it?"}</h2><span class="pane__meta">updated {nice_date(c["updated"])}</span></div>
      <div class="scare">
        {checklist(c)}
        {gauge(s["scare"], INCIDENT_ZONES if inc else None)}
      </div>
    </section>

{timeline_pane(c)}{root_cause_pane(c)}{bug_list(c)}
{affected}    <section class="pane" aria-labelledby="h-do" data-folds>
      <div class="pane__head">
        <h2 id="h-do">{"Clean up" if inc else "What to do"}</h2>
        <button class="link-btn" type="button" data-expand-all>Expand all</button>
      </div>{related}
{fold_items(c["do"])}
    </section>

    <p class="disclaimer">{"This page shows what's known so far. It can't tell you you weren't hit." if is_incident(c) else "This page shows you how to check. It can't tell you you're safe."}</p>
    <details class="sources-fold" id="sources">
      <summary>Sources ({len(c["sources"])}) and changelog</summary>
      <ol class="sources">
{sources}
      </ol>
      <ul class="changes">
{changes}
      </ul>
    </details>
  </main>
"""
    title = f'{c["name"]}{cve_paren(c)} in plain English · tldrcve'
    return page(title, plain(c["tldr"]), body, path=f"/{c['slug']}/", data=f"/{c['slug']}.json")


# ---------- Versions (latest safe version per product line) ----------
# versions/<id>.json holds the newest release on each line; tools/versions.py refreshes it from the vendor's feed.
# Bug pages list their own first fixes in "fixed_in" and embed the product in their upgrade step with "versions",
# so the latest safe version lives in one place.

VERSIONS = {p.stem: json.loads(p.read_text()) for p in sorted(VERSIONS_DIR.glob("*.json"))} if VERSIONS_DIR.exists() else {}


def vkey(v: str) -> tuple:
    """Comparable version: "1.110.0-rc.2" < "1.110.0" < "1.110.1". Text in brackets is ignored."""
    v = re.sub(r"\(.*?\)", "", v)
    m = re.search(r"[-_ .]?(rc|alpha|beta|preview)", v, re.I)
    base, pre = (v[:m.start()], v[m.start():]) if m else (v, "")
    nums = tuple(int(x) for x in re.findall(r"\d+", base))
    return (nums, 0, tuple(int(x) for x in re.findall(r"\d+", pre))) if m else (nums, 1, ())


def product_pages(pid: str, all_c: list) -> list:
    v = VERSIONS.get(pid, {})
    unfixed = {slug for u in v.get("unfixed", []) for slug in u["pages"]}
    return [c for c in all_c if pid in c.get("fixed_in", {}) or c["slug"] in unfixed]


def versions_checks(all_c: list) -> list:
    """Every embedded product exists, and its latest safe version is at or above each page's fix."""
    warnings = []
    slugs = {c["slug"] for c in all_c}
    for c in all_c:
        embedded = {pid for d in c["do"] for pid in d.get("versions", [])}
        for pid in embedded - set(VERSIONS):
            warnings.append(f"{c['slug']}: embeds versions/{pid}.json, which does not exist")
        for pid in set(c.get("fixed_in", {})) - embedded:
            warnings.append(f'{c["slug"]}.fixed_in.{pid}: add "versions": ["{pid}"] to the upgrade step')
        for pid, fixes in c.get("fixed_in", {}).items():
            lines = {l["key"]: l for l in VERSIONS.get(pid, {}).get("lines", [])}
            for key, fixed in fixes.items():
                if key not in lines:
                    warnings.append(f'{c["slug"]}.fixed_in.{pid}.{key}: no such line in versions/{pid}.json')
                elif vkey(lines[key]["latest"]) < vkey(fixed):
                    warnings.append(f'versions/{pid}.json: {key} latest {lines[key]["latest"]} is older than the fix {fixed} '
                                    f'on {c["slug"]}; run python3 tools/versions.py')
    for c in all_c:  # every page is tied to a product on Safe versions, or says why not
        covered = [pid for pid in VERSIONS if c["slug"] in {x["slug"] for x in product_pages(pid, all_c)}]
        if not covered and not c.get("versions_skip"):
            warnings.append(f'{c["slug"]}: not on Safe versions; add fixed_in (fix released) or an unfixed entry in '
                            f'versions/<product>.json (fix pending), or "versions_skip": "<reason>"')
        if covered and c.get("versions_skip"):
            warnings.append(f'{c["slug"]}: has versions_skip but is listed by versions/{covered[0]}.json; remove versions_skip')
    for pid, v in VERSIONS.items():
        for u in v.get("unfixed", []):
            for slug in set(u["pages"]) - slugs:
                warnings.append(f"versions/{pid}.json: unfixed line {u['line']!r} names page {slug}, which does not exist")
        if not product_pages(pid, all_c):
            warnings.append(f"versions/{pid}.json: no page lists it in fixed_in or unfixed")
        if not v["lines"] and not v.get("unfixed"):
            warnings.append(f"versions/{pid}.json: no lines and nothing unfixed")
    return warnings


def version_rows(v: dict, dated: bool) -> str:
    out = []
    for l in v["lines"]:
        note = f'<span class="vline__note">{text(l["note"])}</span>' if l.get("note") else ""
        out.append(f'''          <tr><th scope="row">{text(l["line"])}{note}</th><td class="vline__good">{html.escape(l["latest"])}</td>
            {f'<td>{nice_date(l["released"])}</td>' if l.get("released") else ("<td></td>" if dated else "")}</tr>''')
    for u in v.get("unfixed", []):
        out.append(f'''          <tr class="vline--nofix"><th scope="row">{text(u["line"])}<span class="vline__note">{text(u["note"])}</span></th>
            <td><span class="nofix">No fix</span></td>{"<td></td>" if dated else ""}</tr>''')
    return "\n".join(out)


def product_search(v: dict, pages: list) -> str:
    words = [v["id"], v["name"], v["filter"]]
    words += [l["line"] for l in v["lines"]] + [l["latest"] for l in v["lines"]] + [u["line"] for u in v.get("unfixed", [])]
    for c in pages:
        words += [c["name"], *c["cves"], *c.get("ghsa", []), *c.get("aliases", [])]
    return " ".join(words).lower()


def versions_page(v: dict, all_c: list) -> str:
    pid = v["id"]
    pages = sorted(product_pages(pid, all_c), key=lambda c: c["disclosed"], reverse=True)
    unfixed_pages = {slug for u in v.get("unfixed", []) for slug in u["pages"]}
    bugs = []
    for c in pages:
        if pid in c.get("fixed_in", {}):
            fix = "Fixed in " + html.escape(" · ".join(sorted(c["fixed_in"][pid].values(), key=vkey, reverse=True)))
            for u in v.get("unfixed", []):
                if c["slug"] in u["pages"]:
                    fix += f' · <span class="nofix">{text(u["line"])}: no fix</span>'
        else:
            fix = '<span class="nofix">No fix yet</span>'
        bugs.append(f'''      <li class="vbug"><a href="/{c["slug"]}/">
        <span class="vbug__top"><span class="vbug__name">{html.escape(c["name"])}</span><span class="verdict verdict--{c["verdict"]}">{VERDICTS[c["verdict"]]}</span></span>
        <span class="vbug__meta">{html.escape(cve_list(c) or "No CVE yet")} · {nice_date(c["disclosed"])}</span>
        <span class="vbug__fix">{fix}</span>
      </a></li>''')
    updates = sorted(((ch["date"], c, ch["text"]) for c in pages for ch in c["changes"]), key=lambda x: x[0], reverse=True)[:8]
    upd = "\n".join(f'        <li><time datetime="{d}">{nice_date(d)}</time><span><a href="/{c["slug"]}/">{html.escape(c["name"])}</a>: {text(t)}</span></li>'
                     for d, c, t in updates)
    srcs = " · ".join(f'<a href="{html.escape(s["url"])}">{text(s["title"])}</a>' for s in v["sources"])
    head = "Run at least this" if v["lines"] else "No fix yet"
    dated = any(l.get("released") for l in v["lines"])
    body = f"""  <main class="wrap brief versions-page">
    <div class="toolbar"><a class="back" href="/versions/">{ICONS["back"]}All safe versions</a></div>
    <header class="brief-head">
      <p class="kicker">Latest safe versions</p>
      <h1>{html.escape(v["name"])}</h1>
      <p class="summary">{text(v["about"])}</p>
    </header>

    <section class="pane" aria-labelledby="h-good">
      <div class="pane__head"><h2 id="h-good">{head}</h2><span class="pane__meta">checked {nice_date(v["checked"])}</span></div>
      <div class="vtable">
        <table>
          <thead><tr><th scope="col">Line</th><th scope="col">Latest safe</th>{'<th scope="col">Released</th>' if dated else ""}</tr></thead>
          <tbody>
{version_rows(v, dated)}
          </tbody>
        </table>
        {f'<p class="safe__note">{text(v["older"])}</p>' if v.get("older") else ""}
        <p class="safe__note">From {srcs}.</p>
        <p class="safe__note">Newest releases checked {nice_date(v["checked"])} at {" · ".join(f'<a href="{html.escape(u)}">{html.escape(u.split("//", 1)[-1].split("/", 1)[0])}</a>' for u in v.get("latest_from", []))}.</p>
      </div>
    </section>

    <section class="pane" aria-labelledby="h-bugs">
      <div class="pane__head"><h2 id="h-bugs">Bugs we cover ({len(pages)})</h2><a class="more-link" href="/cves/?q={quote(v["filter"])}">Filter all CVEs →</a></div>
      <ul class="vbugs">
{chr(10).join(bugs)}
      </ul>
    </section>

    <section class="pane" aria-labelledby="h-upd">
      <div class="pane__head"><h2 id="h-upd">Latest updates</h2></div>
      <ul class="changes vchanges">
{upd}
      </ul>
    </section>
  </main>
"""
    return page(f'Latest safe {v["name"]} versions · tldrcve', v["about"], body, current="versions", path=f"/versions/{pid}/", data=f"/versions/{pid}.json")


def versions_index(all_c: list) -> str:
    cards = []
    n_nofix = 0
    for pid, v in sorted(VERSIONS.items(), key=lambda kv: kv[1]["name"].lower()):
        pages = product_pages(pid, all_c)
        n = len(pages)
        nofix = bool(v.get("unfixed"))
        n_nofix += nofix
        chips = "".join(f'<span class="vchip"><span>{text(l["line"])}</span><b>{html.escape(l["latest"])}</b></span>' for l in v["lines"])
        chips += "".join(f'<span class="vchip vchip--nofix"><span>{text(u["line"])}</span><b>No fix</b></span>' for u in v.get("unfixed", []))
        cards.append(f'''      <li class="vcard" data-search="{html.escape(product_search(v, pages))}" data-nofix="{int(nofix)}"><a href="/versions/{pid}/">
        <span class="vcard__top"><span class="vcard__name">{html.escape(v["name"])}</span><span class="vcard__meta">{n} bug{"s" if n != 1 else ""} · checked {nice_date(v["checked"])}</span></span>
        <span class="vchips">{chips}</span>
      </a></li>''')
    body = f"""  <main class="wrap list-page" data-vlist>
    <header class="page-head">
      <h1>Latest safe versions</h1>
      <p>The newest release on each line, with every bug we cover fixed.<br>As far as we know.</p>
    </header>

    <div class="controls">
      <div class="search search--inline" role="search">
        <label for="vlist-q" class="visually-hidden">Filter</label>
        {SEARCH_ICON}
        <input id="vlist-q" type="search" placeholder="Filter by product, version or CVE" autocomplete="off" data-vlist-filter>
      </div>
      <div class="seg" role="group" aria-label="Show">
        <button type="button" data-nofix="" aria-pressed="true">All ({len(VERSIONS)})</button>
        <button type="button" data-nofix="1" aria-pressed="false">No fix yet ({n_nofix})</button>
      </div>
    </div>
    <ul class="vcards">
{chr(10).join(cards)}
    </ul>
    <p class="list__empty" hidden>Nothing matches. Try a product name like PHP or a CVE ID.</p>
  </main>
"""
    return page("Latest safe versions · tldrcve", "The newest safe release on each product line, as far as we know.", body, current="versions", path="/versions/")


# ---------- Weekly review and week ahead ----------
# weeks/<yyyy>-w<nn>.json: {"week": "2026-W47", "intro": ""}. Everything else on the page is derived from the data:
# pages published or changed that week, safe releases that week, and what's coming up in the 30 days after it
# (calendar.json events, pending fixes, CISA KEV deadlines).

WEEKS_DIR = ROOT / "weeks"
CALENDAR_FILE = ROOT / "calendar.json"
CALENDAR = json.loads(CALENDAR_FILE.read_text())["events"] if CALENDAR_FILE.exists() else []
WEEKS = sorted((json.loads(p.read_text()) for p in WEEKS_DIR.glob("*.json")), key=lambda w: w["week"]) if WEEKS_DIR.exists() else []
AHEAD_DAYS = 30
WEEK_TILES = 6  # the scariest new pages get a tile; the rest go in a compact list
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def week_bounds(w: str):
    y, n = WEEK_RE.match(w).groups()
    mon = date.fromisocalendar(int(y), int(n), 1)
    return mon, mon + timedelta(days=6)


def week_slug(w: str) -> str:
    return w.lower()


def week_label(w: str) -> str:
    mon, sun = week_bounds(w)
    if mon.month == sun.month:
        return f"{mon.day}–{sun.day} {sun.strftime('%b %Y')}"
    return f"{mon.day} {mon.strftime('%b')} – {sun.day} {sun.strftime('%b %Y')}"


def week_title(w: str) -> str:
    return f"Week {int(WEEK_RE.match(w).group(2))}"


def upcoming(all_c: list, start: date, end: date) -> list:
    """Scheduled release days, pending fixes and CISA deadlines between start and end, oldest first."""
    out = []
    def within(d):
        return d and start <= date.fromisoformat(d) <= end
    for e in CALENDAR:
        if within(e["date"]):
            out.append({"date": e["date"], "kind": e["kind"], "title": e["title"], "product": e.get("product", ""),
                        "note": e.get("note", ""), "expected": bool(e.get("expected")), "url": e["source"]["url"],
                        "source": e["source"]["title"]})
    for c in all_c:
        for d in c["do"]:
            exp = (d.get("pending") or {}).get("expected")
            if within(exp):
                out.append({"date": exp, "kind": "pending", "title": f'{c["name"]}: {d["label"]}', "product": c["product"],
                            "note": "We'll check again by this date.", "expected": True, "url": f'/{c["slug"]}/', "source": "",
                            "match": page_search(c)})
        kev = c["status"].get("kev")
        if kev and within(kev.get("due")):
            out.append({"date": kev["due"], "kind": "deadline", "title": f'CISA deadline: {c["name"]}', "product": c["product"],
                        "note": "CISA's fix-by date for US federal civilian agencies.", "expected": False, "url": f'/{c["slug"]}/', "source": "",
                        "match": page_search(c)})
    return sorted(out, key=lambda e: (e["date"], e["kind"], e["title"]))


def week_data(w: str, all_c: list) -> dict:
    """A finished week is frozen in its weeks/ file ("snapshot", written by `build.py --freeze-week`), so its page
    stays as it was; the current week is computed from live data."""
    wk = next((x for x in WEEKS if x["week"] == w), {})
    snap = wk.get("snapshot")
    if snap:
        by_slug = {c["slug"]: c for c in all_c}
        return {"week": w, "start": snap["start"], "end": snap["end"],
                "new": [by_slug[s] for s in snap["new"] if s in by_slug],
                "changed": [(dt, by_slug[sl], t) for dt, sl, t in snap["changed"] if sl in by_slug],
                "releases": [(dt, pid, VERSIONS.get(pid, {"name": name}), {"line": line, "latest": latest})
                             for dt, pid, name, line, latest in snap["releases"]],
                "ahead": snap["ahead"]}
    mon, sun = week_bounds(w)
    def in_week(d):
        return d and mon <= date.fromisoformat(d) <= sun
    new = sorted((c for c in all_c if any(ch["text"] == "Published." and in_week(ch["date"]) for ch in c["changes"])),
                 key=lambda c: c["status"]["scare"], reverse=True)
    changed = sorted(((ch["date"], c, ch["text"]) for c in all_c for ch in c["changes"]
                      if ch["text"] != "Published." and in_week(ch["date"])), key=lambda x: (x[0], x[1]["slug"]), reverse=True)
    releases = sorted(((l["released"], pid, v, l) for pid, v in VERSIONS.items() for l in v["lines"] if in_week(l.get("released"))),
                      key=lambda x: (x[0], x[1]), reverse=True)
    return {"week": w, "start": mon.isoformat(), "end": sun.isoformat(), "new": new, "changed": changed,
            "releases": releases, "ahead": upcoming(all_c, sun + timedelta(days=1), sun + timedelta(days=AHEAD_DAYS))}


def ahead_items(ahead: list) -> str:
    rows = []
    for e in ahead:
        ext = e["url"].startswith("http")
        rel = ' rel="nofollow"' if ext else ""
        link = f'<a href="{html.escape(e["url"])}"{rel}>{html.escape(e["title"])}</a>'
        tag = ' <span class="tag">Recheck</span>' if e["kind"] == "pending" else (' <span class="tag">Expected</span>' if e["expected"] else "")
        note = f' <span class="muted">{text(e["note"])}</span>' if e["note"] else ""
        search = " ".join([e["title"], e.get("product", ""), e.get("note", ""), e.get("match", "")]).lower()
        rows.append(f'        <li data-date="{e["date"]}" data-search="{html.escape(search)}"><time datetime="{e["date"]}">{nice_date(e["date"])}</time><span>{link}{tag}{note}</span></li>')
    return "\n".join(rows) or '        <li><span></span><span>Nothing scheduled that we know of.</span></li>'


def week_page(wk: dict, all_c: list) -> str:
    w = wk["week"]
    d = week_data(w, all_c)
    idx = [x["week"] for x in WEEKS].index(w)
    prev_w = WEEKS[idx - 1]["week"] if idx > 0 else None
    next_w = WEEKS[idx + 1]["week"] if idx + 1 < len(WEEKS) else None
    n_upd = len({c["slug"] for _, c, _ in d["changed"]})
    counts = f'{len(d["new"])} new page{"s" if len(d["new"]) != 1 else ""}, {n_upd} page{"s" if n_upd != 1 else ""} updated'
    intro = f'\n      <p>{text(wk["intro"])}</p>' if wk.get("intro") else ""
    by_page = {}
    for dt, c, t in d["changed"]:  # newest first, so the first entry per page is its latest change
        by_page.setdefault(c["slug"], (dt, c, t, []))[3].append(t)
    changed = "\n".join(
        f'        <li data-search="{html.escape(page_search(c) + " " + " ".join(all_t).lower())}"><time datetime="{dt}">{nice_date(dt)}</time><span><a href="/{c["slug"]}/">{html.escape(c["name"])}</a>: {text(t)}'
        + (f' <a class="muted" href="/{c["slug"]}/#sources">+{len(all_t) - 1} earlier</a>' if len(all_t) > 1 else "") + "</span></li>"
        for dt, c, t, all_t in by_page.values()) or '        <li><span></span><span>No updates.</span></li>'
    by_prod = {}
    for dt, pid, v, l in d["releases"]:  # newest first
        by_prod.setdefault((pid, dt), (v, []))[1].append(l["latest"])
    releases = "\n".join(
        f'        <li data-search="{html.escape((pid + " " + v["name"] + " " + " ".join(vers)).lower())}"><time datetime="{dt}">{nice_date(dt)}</time><span><a href="/versions/{pid}/">{html.escape(v["name"])}</a>: {html.escape(", ".join(sorted(vers, key=vkey, reverse=True)))}</span></li>'
        for (pid, dt), (v, vers) in by_prod.items()) or '        <li><span></span><span>None with a release date.</span></li>'
    top, rest = d["new"][:WEEK_TILES], d["new"][WEEK_TILES:]
    rest_block = ""
    new_tiles = "\n".join(tile(c, f' data-search="{html.escape(page_search(c))}"') for c in top)
    new_block = f'    <ul class="tiles">\n{new_tiles}\n    </ul>' if top else '    <p class="muted">No new pages.</p>'
    if rest:
        rest_rows = "\n".join(
            f'        <li data-search="{html.escape(page_search(c) + " " + c["tile_line"].lower())}"><span class="verdict verdict--{c["verdict"]}">{VERDICTS[c["verdict"]]}</span><span><a href="/{c["slug"]}/">{html.escape(c["name"])}</a> <span class="muted">{text(c["tile_line"])}</span></span></li>'
            for c in rest)
        rest_block = f"""
    <section class="pane" data-week-section>
      <div class="pane__head"><h2>Also new</h2><span class="pane__meta">{len(rest)} more, scariest first</span></div>
      <div class="pane__body">
      <ul class="changes week-more">
{rest_rows}
      </ul>
      </div>
    </section>"""
    nav = " · ".join(x for x in [
        f'<a href="/week/{week_slug(prev_w)}/">← {week_title(prev_w)}</a>' if prev_w else "",
        '<a href="/week/">All weeks</a>',
        f'<a href="/week/{week_slug(next_w)}/">{week_title(next_w)} →</a>' if next_w else ""] if x)
    end = date.fromisoformat(d["end"])
    body = f"""  <main class="wrap prose-page">
    <header class="page-head">
      <h1>{week_title(w)}</h1>
      <p>{week_label(w)}: {counts}.</p>{intro}
    </header>
    <div class="search search--week" role="search">
      <label for="wq" class="visually-hidden">Search this week</label>
      {SEARCH_ICON}
      <input id="wq" type="search" placeholder="Search this week: product, CVE ID or name" autocomplete="off" data-week-filter>
    </div>
    <p class="list__empty" data-week-empty hidden>Nothing this week matches. Try <a href="/cves/">all CVEs</a>.</p>

    <div data-week-section>
    <div class="section-head"><h2>New pages</h2></div>
{new_block}
    </div>{rest_block}

    <section class="pane" data-week-section>
      <div class="pane__head"><h2>What changed</h2></div>
      <div class="pane__body">
      <ul class="changes">
{changed}
      </ul>
      </div>
    </section>

    <section class="pane" data-week-section>
      <div class="pane__head"><h2>New safe releases</h2><span class="pane__meta">only product lines where we record a release date</span></div>
      <div class="pane__body">
      <ul class="changes">
{releases}
      </ul>
      </div>
    </section>

    <section class="pane" data-week-section>
      <div class="pane__head"><h2>Coming up</h2><span class="pane__meta">{nice_date((end + timedelta(days=1)).isoformat())} – {nice_date((end + timedelta(days=AHEAD_DAYS)).isoformat())}</span></div>
      <div class="pane__body">
      <ul class="changes">
{ahead_items(d["ahead"])}
      </ul>
      </div>
    </section>

    <p class="week-nav">{nav}</p>
  </main>
"""
    return page(f"{week_title(w)} ({week_label(w)}) · tldrcve", f"The week in vulnerabilities, {week_label(w)}: {counts}, and what's coming up.",
                body, current="week", path=f"/week/{week_slug(w)}/", data=f"/week/{week_slug(w)}.json")


def weeks_index(all_c: list) -> str:
    rows = []
    for wk in reversed(WEEKS):
        w = wk["week"]
        d = week_data(w, all_c)
        rows.append(f'        <li><time datetime="{d["start"]}">{nice_date(d["start"])}</time><span><a href="/week/{week_slug(w)}/">{week_title(w)}</a>: {week_label(w)}, {len(d["new"])} new, {len({c["slug"] for _, c, _ in d["changed"]})} updated</span></li>')
    body = f"""  <main class="wrap prose-page">
    <header class="page-head">
      <h1>Weekly review</h1>
      <p>What came out each week, what changed, and what's coming up.</p>
    </header>
    <section class="pane">
      <div class="pane__body">
      <ul class="changes">
{chr(10).join(rows)}
      </ul>
      </div>
    </section>
  </main>
"""
    return page("Weekly review · tldrcve", "The week in vulnerabilities: new pages, what changed, and what's coming up.",
                body, current="week", path="/week/")


def home_week(all_c: list) -> str:
    """Homepage block: the latest weekly review and the next few dates after it."""
    if not WEEKS:
        return ""
    w = WEEKS[-1]["week"]
    start = max(week_bounds(w)[0], date.today())  # drop what's past when the site is built
    soon = upcoming(all_c, start, start + timedelta(days=AHEAD_DAYS + 30))  # site.js hides dates past since, keeps 6
    empty_row = "\n        <li data-empty hidden><span></span><span>Nothing scheduled that we know of.</span></li>" if soon else ""
    return f"""
    <section class="pane">
      <div class="pane__head"><h2>Coming up</h2><a class="more-link" href="/week/{week_slug(w)}/">{week_title(w)} review →</a></div>
      <div class="pane__body">
      <ul class="changes" data-upcoming="6">
{ahead_items(soon)}{empty_row}
      </ul>
      </div>
    </section>
"""


# ---------- Home ----------

LATEST_COUNT = 6
SEARCH_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'


def news_date(c: dict) -> str:
    """When it hit the news: an old bug can become news later (new attacks, a CISA listing)."""
    return c.get("news", c["disclosed"])


def last_change(c: dict) -> tuple:
    """When the page itself last changed, for "Latest": (date, "Added" or "Updated")."""
    d = next(ch["date"] for ch in c["changes"] if not ch.get("minor"))  # minor edits don't move a page up
    added = any(ch["text"] == "Published." and ch["date"] == d for ch in c["changes"])
    return d, "Added" if added else "Updated"


def page_search(c: dict) -> str:
    """Lowercase text a filter can match: name, products, CVE/GHSA IDs and aliases."""
    return " ".join([c["name"], product_full(c), *c["cves"], *c.get("ghsa", []), *c.get("aliases", [])]).lower()


def tile(c: dict, attrs: str = "", when: str = "") -> str:
    v = c["verdict"]
    when = when or nice_date(news_date(c))
    return f"""      <li{attrs}>
        <a class="tile" href="/{c["slug"]}/">
          <span class="tile__meta"><span class="tile__product">{html.escape(product_short(c))}</span><span>· {when}</span></span>
          <span class="tile__name">{html.escape(c["name"])}</span>
          <span class="tile__line">{text(c["tile_line"])}</span>
          <span class="tile__foot">{badge(c)}{roundup_tag(c)}{mini_meter(c["status"]["scare"])}</span>
        </a>
      </li>"""


def zones_list(zones: list = None) -> str:
    rows = "\n".join(
        f'        <li>{mini_meter(i + 0.5)}<strong>{label}</strong><span>{hint}</span></li>'
        for i, (_, label, hint) in enumerate(zones or ZONES)
    )
    return f'      <ul class="zones">\n{rows}\n      </ul>'


def home(all_c: list) -> str:
    # Latest = what changed on tldrcve most recently (new pages and updates), newest first.
    latest = sorted(all_c, key=lambda c: (last_change(c)[0], last_change(c)[1] == "Added", news_date(c)), reverse=True)[:LATEST_COUNT]
    body = f"""  <main class="wrap home">
    <section class="hero">
      <h1>CVEs in plain English</h1>
      <p class="hero__lede">The vulnerabilities and attacks everyone's panicking about.<br>Are you affected, and what should you do?</p>
      <form class="search" role="search" action="/cves/" method="get">
        <label for="q" class="visually-hidden">Search all CVEs</label>
        {SEARCH_ICON}
        <input id="q" name="q" type="search" placeholder="CVE ID, product or nickname" autocomplete="off">
      </form>
    </section>

    <div class="section-head">
      <h2>Latest</h2>
      <a class="more-link" href="/cves/">Browse all CVEs →</a>
    </div>
    <ul class="tiles">
{chr(10).join(tile(c, when=f"{last_change(c)[1]} {nice_date(last_change(c)[0])}") for c in latest)}
    </ul>
{home_week(all_c)}
    <section class="pane rate">
      <div class="pane__head"><h2>The scare-o-meter</h2><a class="more-link" href="/how-we-rate/">How we rate →</a></div>
{zones_list()}
    </section>
  </main>
"""
    return page("tldrcve: CVEs in plain English",
                "The vulnerabilities and attacks everyone's talking about, in plain English: are you affected, and what to do.",
                body, current="home", path="/")


# ---------- All CVEs ----------

def cves_page(all_c: list) -> str:
    vulns = [c for c in all_c if not is_incident(c)]  # incidents have their own list,
    incs = [c for c in all_c if is_incident(c)]       # but a search here finds them too
    ordered = sorted(vulns, key=lambda c: c["status"]["scare"], reverse=True) + incs
    rows = []
    for c in ordered:
        v = c["verdict"]
        search = " ".join([c["name"], product_full(c), *c["cves"], *c.get("ghsa", []), *c.get("aliases", [])]).lower()
        rows.append(
            f"""      <li class="row{" row--incident" if is_incident(c) else ""}" data-search="{html.escape(search)}" data-scare="{c["status"]["scare"]}" data-disclosed="{c["disclosed"]}"{' data-incident="1" hidden' if is_incident(c) else ""}>
        <a href="/{c["slug"]}/">
          <span class="row__meter">{mini_meter(c["status"]["scare"])}</span>
          <span class="row__main">
            <span class="row__name">{html.escape(c["name"])}</span>
            <span class="row__meta">{html.escape(product_short(c))} · {html.escape(cve_list(c) or "No CVE yet")}</span>
          </span>
          <span class="row__line">{text(c["tile_line"])}</span>
          <span class="row__verdict">{badge(c)}{roundup_tag(c)}</span>
          <time class="row__date" datetime="{c["disclosed"]}">{nice_date(c["disclosed"])}</time>
        </a>
      </li>"""
        )
    body = f"""  <main class="wrap list-page" data-list>
    <header class="page-head">
      <h1>All CVEs</h1>
      <p>{len(vulns)} vulnerabilities people are actually asking about. Nothing else. Attacks that already happened are under <a href="/incidents/">Incidents</a>.</p>
    </header>

    <div class="controls">
      <div class="search search--inline" role="search">
        <label for="list-q" class="visually-hidden">Filter</label>
        {SEARCH_ICON}
        <input id="list-q" type="search" placeholder="Filter by CVE, product or nickname" autocomplete="off" data-list-filter>
      </div>
      <div class="seg" role="group" aria-label="Sort by">
        <button type="button" data-sort="scare" aria-pressed="true">Most important</button>
        <button type="button" data-sort="recent" aria-pressed="false">Most recent</button>
      </div>
      <div class="seg" role="group" aria-label="Released">
        <button type="button" data-days="7" aria-pressed="false">7 days</button>
        <button type="button" data-days="30" aria-pressed="false">30 days</button>
        <button type="button" data-days="90" aria-pressed="false">90 days</button>
        <button type="button" data-days="" aria-pressed="true">All time</button>
      </div>
    </div>

    <div class="pane list">
      <div class="list__head" aria-hidden="true">
        <span>Scare</span><span>Vulnerability</span><span>In short</span><span>Verdict</span><span>Released</span>
      </div>
      <ol class="rows">
{chr(10).join(rows)}
      </ol>
      <p class="list__empty" hidden>No CVEs match. Try a wider date range, or a different search.</p>
    </div>
  </main>
"""
    return page("All CVEs · tldrcve", "Every CVE we cover, sorted by how scary it is or how recent.",
                body, current="cves", path="/cves/")


# ---------- Incidents ----------

def incidents_page(all_c: list) -> str:
    incs = sorted((c for c in all_c if is_incident(c)), key=lambda c: c["status"]["scare"], reverse=True)
    rows = []
    for c in incs:
        when, verb = last_change(c)
        entry = entry_tag(c["incident"]["checks"]["entry"]["state"])
        search = " ".join([c["name"], product_full(c), *(o["name"] for o in c.get("orgs", [])), *c["cves"],
                           *c.get("aliases", [])]).lower()
        rows.append(f"""      <li class="row" data-search="{html.escape(search)}" data-scare="{c["status"]["scare"]}" data-disclosed="{when}">
        <a href="/{c["slug"]}/">
          <span class="row__meter">{mini_meter(c["status"]["scare"])}</span>
          <span class="row__main">
            <span class="row__name">{html.escape(c["name"])}</span>
            <span class="row__meta">{html.escape(product_short(c))} · {html.escape(cve_list(c) or "No CVE")}</span>
          </span>
          <span class="row__line">{text(c["tile_line"])}</span>
          <span class="row__verdict">{entry}</span>
          <time class="row__date" datetime="{when}">{verb} {nice_date(when)}</time>
        </a>
      </li>""")
    body = f"""  <main class="wrap list-page" data-list>
    <header class="page-head">
      <h1>Incidents</h1>
      <p>Attacks that already happened. <a href="/how-we-rate/#incidents">How we rate them</a>.</p>
    </header>

    <div class="controls">
      <div class="search search--inline" role="search">
        <label for="list-q" class="visually-hidden">Filter</label>
        {SEARCH_ICON}
        <input id="list-q" type="search" placeholder="Filter by organisation, product or CVE" autocomplete="off" data-list-filter>
      </div>
      <div class="seg" role="group" aria-label="Sort by">
        <button type="button" data-sort="scare" aria-pressed="true">Most severe</button>
        <button type="button" data-sort="recent" aria-pressed="false">Most recent</button>
      </div>
      <div class="seg" role="group" aria-label="Updated">
        <button type="button" data-days="7" aria-pressed="false">7 days</button>
        <button type="button" data-days="30" aria-pressed="false">30 days</button>
        <button type="button" data-days="90" aria-pressed="false">90 days</button>
        <button type="button" data-days="" aria-pressed="true">All time</button>
      </div>
    </div>

    <div class="pane list list--incidents">
      <div class="list__head" aria-hidden="true">
        <span>Impact</span><span>Incident</span><span>In short</span><span>How they got in</span><span>Last change</span>
      </div>
      <ol class="rows">
{chr(10).join(rows)}
      </ol>
      <p class="list__empty" hidden>No incidents match. Try a wider date range, or a different search.</p>
    </div>
  </main>
"""
    return page("Incidents · tldrcve", "Attacks that already happened: what's confirmed, how bad it is, and what to clean up.",
                body, current="incidents", path="/incidents/")


# ---------- How we rate ----------

def entry_tag(state: str) -> str:
    return f'<span class="tag tag--entry tag--entry-{state}">{ENTRY_TAGS[state]}</span>'


def how_page() -> str:
    who = "\n".join(f'        <dt><span class="who who--{k}">{v}</span></dt><dd>{WHO_HELP[k]}</dd>' for k, v in WHO_LABELS.items())
    causes = "\n".join(f'        <dt>{v}</dt><dd>{ROOT_CAUSE_HELP[k]}</dd>' for k, v in ROOT_CAUSES.items())
    checks = "\n".join(f'        <dt>{words["yes"]}</dt><dd>{INCIDENT_CHECK_HELP[key]}</dd>' for key, words in INCIDENT_CHECKS)
    body = f"""  <main class="wrap prose-page">
    <header class="page-head">
      <h1>How we rate</h1>
      <p>We rate CVEs and incidents differently. Pick one:</p>
      <div class="seg tabs" role="tablist" aria-label="Page kind" data-tabs>
        <button type="button" role="tab" data-tab="cves" aria-pressed="true">CVEs</button>
        <button type="button" role="tab" data-tab="incidents" aria-pressed="false">Incidents</button>
      </div>
    </header>

    <div class="tabpanel" data-tabpanel="cves" id="cves">
    <section class="pane">
      <div class="pane__head"><h2>CVEs</h2></div>
      <div class="pane__body intro">
        <p>We cover the CVEs people are talking about, especially the ones attackers are already using. Each page tells you straight away how scary it is and what to do, then how to check whether you're affected and, if you are, how to fix it.</p>
        <p>Listed under <a href="/cves/">All CVEs</a>.</p>
      </div>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>The scare-o-meter</h2></div>
{zones_list()}
      <div class="pane__body">
        <p>What moves the needle, biggest first: <strong>attacks seen in the wild</strong>, a listing on <strong>CISA's exploited list</strong>, <strong>public exploit code</strong>, whether it <strong>works without logging in</strong>, and <strong>how common</strong> the affected setup is. A scary CVSS score on its own doesn't move it.</p>
      </div>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>Verdicts</h2></div>
      <dl class="defs">
        <dt><span class="verdict verdict--now">Patch now</span></dt><dd>Working exploit or attacks seen, and common setups are exposed.</dd>
        <dt><span class="verdict verdict--if">Patch now if…</span></dt><dd>Serious, but only under conditions we list. Each page shows you how to check them.</dd>
        <dt><span class="verdict verdict--cycle">Next cycle</span></dt><dd>Real, but hard to reach or low impact. Patch on your normal schedule.</dd>
        <dt><span class="verdict verdict--watch">Watching</span></dt><dd>People are talking about it, but too little is known to act on. We say what would change that, and update the page when it does.</dd>
      </dl>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>The checklist</h2></div>
      <dl class="defs">
        <dt>Works without logging in</dt><dd>The attacker needs no account, password or certificate.</dd>
        <dt>Public exploit code is out</dt><dd>Working code anyone can download. A blog post or video doesn't count, and neither do the fake exploits that show up after every big CVE.</dd>
        <dt>Shown working</dt><dd>A researcher demonstrated it, but hasn't published the code.</dd>
        <dt>Attacks seen in the wild</dt><dd>A credible report from the vendor, CISA or a named security team.</dd>
        <dt>On CISA's exploited list</dt><dd>Listed in CISA's <a href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog">Known Exploited Vulnerabilities</a> catalog. The fix-by date is CISA's deadline for US federal civilian agencies, which is a good default for everyone else.</dd>
      </dl>
    </section>
    </div>

    <div class="tabpanel" data-tabpanel="incidents" id="incidents">
    <section class="pane">
      <div class="pane__head"><h2>Incidents</h2></div>
      <div class="pane__body intro">
        <p>An incident is an attack that already happened to someone, often at a provider you rely on, so there may be nothing for you to patch. We tell you what happened, how bad it is and who says so, then whether you were hit and what to clean up. Instead of a patch verdict, an incident carries an <span class="verdict verdict--incident">Incident</span> badge.</p>
        <p>Listed under <a href="/incidents/">Incidents</a>.</p>
      </div>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>The scare-o-meter</h2></div>
      <div class="pane__body"><p>The same meter, but it answers "how bad is it?" instead of "how fast should I patch?":</p></div>
{zones_list(INCIDENT_ZONES)}
      <div class="pane__body">
        <p>It's set by the checklist below. A famous name on its own doesn't move it.</p>
      </div>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>The checklist</h2></div>
      <div class="pane__body"><p>Each line is a yes, a partly or a no, with a source.</p></div>
      <dl class="defs">
{checks}
      </dl>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>How they got in</h2></div>
      <dl class="defs">
        <dt>{entry_tag("yes")}</dt><dd>The victim, vendor or investigators have said how the attackers got in.</dd>
        <dt>{entry_tag("part")}</dt><dd>A flaw or route is named, but not explained.</dd>
        <dt>{entry_tag("no")}</dt><dd>Nobody has said how they got in. Treat any theory as a guess.</dd>
      </dl>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>What's confirmed: who says it</h2></div>
      <div class="pane__body"><p>Every line in an incident's timeline is labelled by its source:</p></div>
      <dl class="defs">
{who}
      </dl>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>Root causes</h2></div>
      <dl class="defs">
{causes}
      </dl>
    </section>
    </div>

    <section class="pane">
      <div class="pane__head"><h2>House rules</h2></div>
      <ul class="rules">
        <li><strong>Every claim has a source.</strong> Click the little numbers.</li>
        <li><strong>Every change is logged.</strong> Facts move fast in the first days. Each page has a changelog.</li>
        <li><strong>We show you how to check.</strong> We never tell you you're safe.</li>
        <li><strong>We skip the noise.</strong> We only cover the CVEs and incidents people are actually asking about.</li>
        <li><strong>We get things wrong sometimes.</strong> Tell us on X (<a href="https://x.com/{X_HANDLE}">@{X_HANDLE}</a>) and we'll fix it, in the open.</li>
      </ul>
    </section>
  </main>
"""
    return page("How we rate · tldrcve", "How tldrcve rates CVEs and incidents, and what each label means.",
                body, current="how", path="/how-we-rate/")


RELATIVE = re.compile(r"\b(today|tomorrow|yesterday|tonight|this (morning|afternoon|evening|week))\b", re.I)


NAME_MAX = 18  # fits one line on the narrowest card (checked in the browser at 930px)
PRODUCT_MAX = 26  # card label before the date, in a monospace font


WATCH_DECISIONS = ("watch", "page", "dropped")
VERSIONS_STALE_DAYS = 14


def watch_checks(all_c: list) -> tuple:
    """watch/<id>.json records vulnerabilities we evaluated but haven't (yet) written a page for.
    Returns (warnings, notes): broken entries fail --strict; an overdue recheck is a note."""
    warnings, notes = [], []
    covered = {cve: c["slug"] for c in all_c for cve in c["cves"]}
    for f in sorted(WATCH_DIR.glob("*.json")) if WATCH_DIR.exists() else []:
        w = json.loads(f.read_text())
        name = f"watch/{f.name}"
        for key in ("id", "title", "cves", "evaluated", "decision", "why", "facts", "sources", "history"):
            if key not in w:
                warnings.append(f"{name}: missing {key!r}")
        if w.get("decision") not in WATCH_DECISIONS:
            warnings.append(f"{name}: decision must be one of {', '.join(WATCH_DECISIONS)}")
        n_src = len(w.get("sources", []))
        for i, fact in enumerate(w.get("facts", [])):
            if not fact.get("cite") or any(not 1 <= x <= n_src for x in fact["cite"]):
                warnings.append(f"{name}.facts[{i}]: needs a cite in range 1..{n_src}")
        if w.get("decision") == "watch":
            if not w.get("recheck"):
                warnings.append(f"{name}: a watched item needs a 'recheck' date")
            elif w["recheck"] < date.today().isoformat():
                notes.append(f"{name}: recheck was due {w['recheck']}; look again and log it in 'history'")
            for cve in w.get("cves", []):
                if cve in covered:
                    warnings.append(f"{name}: {cve} now has a page ({covered[cve]}); set decision to 'page' and 'page': '{covered[cve]}'")
    for pid, v in VERSIONS.items():
        if not v.get("latest_from"):
            warnings.append(f"versions/{pid}.json: add 'latest_from', the URL(s) where the newest releases are checked")
        age = (date.today() - date.fromisoformat(v["checked"])).days
        if age > VERSIONS_STALE_DAYS:
            notes.append(f"versions/{pid}.json: last checked {v['checked']} ({age} days ago); refresh it (python3 tools/versions.py --report)")
    return warnings, notes


def card_checks(all_c: list) -> tuple:
    """Link-preview images are rendered by tools/cards.py. Returns (missing, stale) warnings.
    A page with no card at all always fails --strict; a card that's only out of date fails --public."""
    sys.path.insert(0, str(ROOT / "tools"))
    import cards
    made = json.loads((ASSETS / "og" / "cards.json").read_text()) if (ASSETS / "og" / "cards.json").exists() else {}
    keys = cards.expected_keys(all_c)
    missing = [s for s in keys if not (ASSETS / "og" / f"{s}.png").exists()]
    stale = [s for s, k in keys.items() if s not in missing and made.get(s) != k]
    fix = "run python3 tools/cards.py"
    return ([f"no link-preview image for {', '.join(missing)}: {fix}"] if missing else [],
            [f"link-preview image out of date for {', '.join(stale)}: {fix}"] if stale else [])


def editor_checks(all_c: list) -> list:
    """Warnings for things that go stale on a static site."""
    warnings = []

    def strings(obj, path):
        if isinstance(obj, str):
            yield path, obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from strings(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from strings(v, f"{path}[{i}]")

    for c in all_c:
        if c.get("kind", "vulnerability") not in KINDS:
            warnings.append(f'{c["slug"]}: kind must be one of {", ".join(KINDS)}')
        if is_incident(c):
            checks = c.get("incident", {}).get("checks", {})
            for key, _ in INCIDENT_CHECKS:
                ch = checks.get(key, {})
                if ch.get("state") not in ("yes", "part", "no") or not ch.get("cite"):
                    warnings.append(f'{c["slug"]}: incident.checks.{key} needs a state (yes, part, no) and a cite')
            tags = c.get("root_cause", {}).get("tags", [])
            if not tags or any(t not in ROOT_CAUSES for t in tags):
                warnings.append(f'{c["slug"]}: incidents need root_cause.tags from {", ".join(ROOT_CAUSES)}')
        for r in c.get("related", []):
            if r not in PAGES:
                warnings.append(f'{c["slug"]}: related page "{r}" does not exist')
        for i, e in enumerate(c.get("timeline", [])):
            if e.get("who") not in WHO_LABELS:
                warnings.append(f'{c["slug"]}.timeline[{i}]: who must be one of {", ".join(WHO_LABELS)}')
        if len(c["tldr"]) > TLDR_MAX:
            warnings.append(f'{c["slug"]}.tldr is {len(c["tldr"])} chars, keep it to {TLDR_MAX} so the X post with its link fits 280')
        if len(product_short(c)) > PRODUCT_MAX:
            warnings.append(f'{c["slug"]}: card label "{product_short(c)}" is {len(product_short(c))} chars, keep it to {PRODUCT_MAX} so it fits without "…"')
        newest = max(ch["date"] for ch in c["changes"])
        if c["updated"] > newest:
            warnings.append(f'{c["slug"]}: updated {c["updated"]} but the newest changelog entry is {newest}; log what changed')
        n_src = len(c["sources"])
        wanted = ["exploit", "attacks", "kev"] + (["no_login"] if "no_login" in c["status"] else [])
        for k in wanted:
            cs = c.get("status_cite", {}).get(k, [])
            if not cs:
                warnings.append(f'{c["slug"]}.status_cite.{k}: checklist fact has no source')
            elif any(not 1 <= x <= n_src for x in cs):
                warnings.append(f'{c["slug"]}.status_cite.{k}: cite out of range (1..{n_src})')
        if c["status"].get("no_login") is False and not c["status"].get("needs"):
            warnings.append(f'{c["slug"]}.status: no_login is false, so set "needs" (e.g. "a LiteLLM admin key")')
        if len(c["name"]) > NAME_MAX:
            warnings.append(f'{c["slug"]}.name: "{c["name"]}" is {len(c["name"])} chars, keep it to {NAME_MAX} so it fits on one line')
        for path, val in strings(c, c["slug"]):
            m = RELATIVE.search(val)
            if m:
                warnings.append(f"{path}: relative date '{m.group(0)}', use an absolute date")
        for section in ("affected", "do"):
            for i, e in enumerate(c.get(section, [])):
                exp = (e.get("pending") or {}).get("expected")
                if exp and date.fromisoformat(exp) < date.today():
                    warnings.append(f"{c['slug']}.{section}[{i}]: pending item was due {exp}, check and update it")
    for i, e in enumerate(CALENDAR):
        where = f"calendar.json events[{i}] ({e.get('title', '?')})"
        try:
            when = date.fromisoformat(e["date"])
        except (KeyError, ValueError):
            warnings.append(f"{where}: needs a YYYY-MM-DD date")
            continue
        if not (e.get("source") or {}).get("url", "").startswith("https://"):
            warnings.append(f"{where}: needs a source with an https URL")
        if e.get("kind") not in ("release", "patch-day"):
            warnings.append(f"{where}: kind must be release or patch-day")
        if e.get("expected") and when < date.today():
            warnings.append(f"{where}: expected date {e['date']} has passed; confirm it or remove it")
        if not e.get("note"):
            warnings.append(f"{where}: needs a note: whose schedule it is and what it means for readers (shown under Coming up)")
    for e in CALENDAR:
        if RELATIVE.search(e.get("note", "")):
            warnings.append(f"calendar.json ({e.get('title')}): relative date in note, use an absolute date")
    for wk in WEEKS:
        if not WEEK_RE.match(wk.get("week", "")):
            warnings.append(f"weeks: bad week id {wk.get('week')!r}, use YYYY-Www")
            continue
        if RELATIVE.search(wk.get("intro", "")):
            warnings.append(f"weeks/{week_slug(wk['week'])}.json: relative date in intro, use an absolute date")
    return warnings


# Builds without --public tell search engines to stay out (handy for previews).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://static.cloudflareinsights.com",  # Cloudflare Web Analytics beacon
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self' https://cloudflareinsights.com",
    "form-action 'self'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "object-src 'none'",
])


X_HANDLE = "tldrcve"
AUTHOR_HANDLE = "s_streichsbier"
REPO_URL = "https://github.com/streichsbaer/tldrcve"
# Cloudflare Web Analytics (cookieless). Empty token = no analytics snippet.
CF_ANALYTICS_TOKEN = ""
ANALYTICS = (f'  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
             f'data-cf-beacon=\'{{"token": "{CF_ANALYTICS_TOKEN}"}}\'></script>') if CF_ANALYTICS_TOKEN else ""


def social_tags(title: str, description: str, path: str) -> str:
    """Canonical URL plus the tags X, Slack and LinkedIn use for link previews."""
    if path == "404":
        return '  <meta name="robots" content="noindex">'
    url = SITE_URL + (path or "/")
    t, d = html.escape(title), html.escape(description)
    img, _ = og_image(path)
    return "\n".join([
        f'  <link rel="canonical" href="{url}">',
        f'  <meta property="og:type" content="website">',
        f'  <meta property="og:site_name" content="tldrcve">',
        f'  <meta property="og:title" content="{t}">',
        f'  <meta property="og:description" content="{d}">',
        f'  <meta property="og:url" content="{url}">',
        f'  <meta property="og:image" content="{img}">',
        f'  <meta property="og:image:width" content="1200">',
        f'  <meta property="og:image:height" content="630">',
        f'  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:site" content="@{X_HANDLE}">',
    ])


def write_sitemap(all_c: list) -> None:
    newest = max(c["updated"] for c in all_c)
    urls = [("/", newest), ("/cves/", newest), ("/incidents/", newest), ("/versions/", newest),
            ("/how-we-rate/", newest)]
    urls += [(f"/versions/{pid}/", v["checked"]) for pid, v in sorted(VERSIONS.items())]
    urls += [(f'/{c["slug"]}/', c["updated"]) for c in sorted(all_c, key=lambda c: c["slug"])]
    if WEEKS:
        urls.append(("/week/", newest))
        urls += [(f'/week/{week_slug(w["week"])}/', min(newest, week_bounds(w["week"])[1].isoformat())) for w in WEEKS]
    body = "\n".join(f"  <url><loc>{SITE_URL}{p}</loc><lastmod>{d}</lastmod></url>" for p, d in urls)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>\n")


FEED_ITEMS = 60
FEED_ABOUT = "The vulnerabilities everyone's talking about, in plain English. New pages, and updates that change what you should know or do."
# (path prefix, title, description, which pages, weekly reviews too). /feed.xml stays CVEs only, as it always was, so
# existing subscribers don't start getting incidents they didn't sign up for.
FEEDS = [
    ("", "tldrcve: CVEs", FEED_ABOUT, lambda c: not is_incident(c), True),
    ("/incidents", "tldrcve: incidents",
     "Attacks that already happened, in plain English: how bad it is, who says so, and what to clean up. New pages, and updates that change what you should know or do.",
     lambda c: is_incident(c), False),
    ("/all", "tldrcve: CVEs and incidents", FEED_ABOUT + " Incidents included.", lambda c: True, True),
]
FEED_LINKS = "\n".join(
    f'  <link rel="alternate" type="application/rss+xml" title="{t}" href="{p}/feed.xml">\n'
    f'  <link rel="alternate" type="application/feed+json" title="{t} (JSON Feed)" href="{p}/feed.json">' for p, t, *_ in FEEDS)


def item_image(url: str, size: int) -> str:
    """An item's preview image: <enclosure> for RSS readers, media:content and media:thumbnail for chat apps."""
    u = html.escape(url)
    return (f'      <enclosure url="{u}" length="{size}" type="image/png"/>\n'
            f'      <media:content url="{u}" medium="image" type="image/png" width="1200" height="630"/>\n'
            f'      <media:thumbnail url="{u}" width="1200" height="630"/>')


# Items the feed already published under the old position-based GUIDs (before 24 Nov 2026). Keeping their old IDs stops
# readers from showing them again. Safe to delete once these dates have scrolled out of the feed.
LEGACY_GUIDS = {
    "linux-sctp-root-2026-11-22-0": "linux-sctp-root-2026-11-22-1",
    "citrix-netscaler-2026-11-21-0": "citrix-netscaler-2026-11-21-1",
    "react-typed-array-rce-2026-11-21-0": "react-typed-array-rce-2026-11-21-1",
    "wordpress-7-1-5-2026-11-21-0": "wordpress-7-1-5-2026-11-21-1",
    "nextjs-image-rce-2026-11-21-0": "nextjs-image-rce-2026-11-21-1",
    "brotli-2026-11-20-0": "brotli-2026-11-20-1",
}


def feed_entries(all_c: list, weeks: bool = True) -> list:
    """One entry per changelog line across the given pages (newest first), then one per weekly review. Shared by RSS and JSON Feed.
    Entries marked "minor" (wording, sources, rechecks that changed nothing) stay on the page and out of the feeds."""
    changes = sorted(((ch["date"], -i, c, ch["text"]) for c in all_c for i, ch in enumerate(c["changes"]) if not ch.get("minor")),
                     key=lambda e: (e[0], e[1]), reverse=True)[:FEED_ITEMS]
    out = []
    for d, neg_i, c, t in changes:
        # Stable GUID: page, date, and how many newer entries the page has on that same date. A new entry on a later
        # date never renames an older item, so readers don't show it again. (Same-day edits go into one entry.)
        nth = sum(1 for ch in c["changes"][:-neg_i] if ch["date"] == d)
        new = t == "Published."
        s = c["status"]
        tags = [("type", "New page" if new else "Update"), ("verdict", badge_text(c)),
                ("scare", zone(s["scare"])[0]), ("exploit", EXPLOIT_LABELS[s["exploit"]][1]),
                ("attacks", ATTACK_LABELS[s["attacks"]][1])]
        if s.get("kev"):
            tags.append(("kev", "On CISA's exploited list"))
        tags += [("product", c["product"])] + [("cve", x) for x in c["cves"]]
        out.append({
            "id": LEGACY_GUIDS.get(f'{c["slug"]}-{d}-{nth}', f'{c["slug"]}-{d}-{nth}'), "date": d, "url": f'{SITE_URL}/{c["slug"]}/', "page": c,
            "title": f'{"" if new else "Update: "}{c["name"]} ({cve_list(c) or "no CVE yet"})',
            # A new page: the TL;DR, then More details. An update: what changed, then where things stand now.
            "text": plain(f'{c["tldr"]}\n\n{c["summary"]}' if new else f'What changed: {t}\n\nNow: {c["tldr"]}'),
            "html": (f'<p>{html.escape(plain(c["tldr"]))}</p>\n<p>{html.escape(plain(c["summary"]))}</p>' if new else
                     f'<p><strong>What changed:</strong> {html.escape(plain(t))}</p>\n<p><strong>Now:</strong> {html.escape(plain(c["tldr"]))}</p>'),
            "image": og_image(f'/{c["slug"]}/'), "tags": tags, "json": f'{SITE_URL}/{c["slug"]}.json'})
    for wk in WEEKS if weeks else []:
        w = wk["week"]
        d = week_data(w, all_c)
        out.append({
            "id": f"week-{week_slug(w)}", "date": d["end"], "url": f"{SITE_URL}/week/{week_slug(w)}/", "page": None,
            "title": f"{week_title(w)} review ({week_label(w)})",
            "text": f'{len(d["new"])} new pages, {len({c["slug"] for _, c, _ in d["changed"]})} pages updated, and {len(d["ahead"])} dates coming up.',
            "html": f'<p>{len(d["new"])} new pages, {len({c["slug"] for _, c, _ in d["changed"]})} pages updated, and {len(d["ahead"])} dates coming up.</p>',
            "image": og_image(f"/week/{week_slug(w)}/"), "tags": [("type", "Weekly review")],
            "json": f"{SITE_URL}/week/{week_slug(w)}.json"})
    return out


def write_feeds(all_c: list) -> None:
    """Every feed in FEEDS, each as RSS 2.0 (feed.xml) and JSON Feed 1.1 (feed.json). An item has the same ID in every
    feed, so a reader subscribed to two of them shows it once."""
    for prefix, title, about, keep, weeks in FEEDS:
        write_feed([c for c in all_c if keep(c)], prefix, title, about, weeks)


def write_feed(pages: list, prefix: str, title: str, about: str, weeks: bool) -> None:
    """RSS 2.0 at <prefix>/feed.xml and JSON Feed 1.1 at <prefix>/feed.json, with the same items."""
    from email.utils import format_datetime
    from datetime import datetime, timezone
    entries = feed_entries(pages, weeks)
    out_dir = OUT / prefix.strip("/")
    out_dir.mkdir(parents=True, exist_ok=True)

    def when(d):  # noon UTC on that day, but never later than the build itself (validators flag future dates)
        return min(datetime.fromisoformat(d).replace(hour=12, tzinfo=timezone.utc), datetime.now(timezone.utc).replace(microsecond=0))

    items = []
    for e in entries:
        cats = "\n".join(f'      <category domain="{k}">{html.escape(v)}</category>' for k, v in e["tags"])
        items.append(f"""    <item>
      <title>{html.escape(e["title"])}</title>
      <link>{e["url"]}</link>
      <guid isPermaLink="false">{e["id"]}</guid>
      <pubDate>{format_datetime(when(e["date"]))}</pubDate>
      <description>{html.escape(e["html"])}</description>
{item_image(*e["image"])}
{cats}
    </item>""")
    newest = max((e["date"] for e in entries), default=date.today().isoformat())
    (out_dir / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>{title}</title>
    <link>{SITE_URL}{prefix}/</link>
    <atom:link href="{SITE_URL}{prefix}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>{html.escape(about)}</description>
    <language>en</language>
    <lastBuildDate>{format_datetime(when(newest))}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
""")

    def extra(e):
        c = e["page"]
        if c is None:
            return {"type": "weekly-review", "json": e["json"]}
        s = c["status"]
        return {"type": "new" if e["tags"][0][1] == "New page" else "update", "slug": c["slug"], "json": e["json"],
                "product": c["product"], "cves": c["cves"], "verdict": c["verdict"], "scare": s["scare"],
                "exploit": s["exploit"], "attacks": s["attacks"], "kev": s.get("kev"), "no_login": s.get("no_login")}

    feed = {
        "version": "https://jsonfeed.org/version/1.1", "title": title, "home_page_url": f"{SITE_URL}{prefix}/",
        "feed_url": f"{SITE_URL}{prefix}/feed.json", "description": about, "language": "en",
        "icon": f"{SITE_URL}/assets/icons/apple-touch-icon.png", "favicon": f"{SITE_URL}/assets/icons/icon-32.png",
        "items": [{"id": e["id"], "url": e["url"], "title": e["title"], "content_text": e["text"], "content_html": e["html"],
                   "image": e["image"][0], "date_published": when(e["date"]).isoformat(),
                   "tags": [v for _, v in e["tags"]], "_tldrcve": extra(e)} for e in entries]}
    (out_dir / "feed.json").write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n")


def write_redirects(all_c: list) -> None:
    """tldrcve.com/CVE-2026-114938 or /GHSA-xxxx-xxxx-xxxx goes straight to the page (Cloudflare reads _redirects)."""
    lines, seen = [], {}
    for c in all_c:
        for ident in c["cves"] + c.get("ghsa", []):
            for form in (ident.upper() if ident.upper().startswith("CVE") else "GHSA-" + ident[5:].lower(), ident.lower()):
                if seen.setdefault(form, c["slug"]) != c["slug"]:
                    raise SystemExit(f"{form} is claimed by both {seen[form]} and {c['slug']}")
                lines += [f"/{form} /{c['slug']}/ 301", f"/{form}/ /{c['slug']}/ 301"]
    (OUT / "_redirects").write_text("\n".join(dict.fromkeys(lines)) + "\n")


# ---------- Data for agents: /llms.txt, /<slug>.json, /versions/<id>.json, /api/cves.json ----------

def scare_label(scare: float) -> str:
    return zone(scare)[0]


def version_data(pid: str, all_c: list) -> dict:
    """versions/<id>.json as published, plus its URLs and the pages it covers."""
    v = VERSIONS[pid]
    return {"url": f"{SITE_URL}/versions/{pid}/", "json": f"{SITE_URL}/versions/{pid}.json", **v,
            "pages": [c["slug"] for c in product_pages(pid, all_c)]}


def page_data(c: dict) -> dict:
    """content/<slug>.json as published, plus URLs, labels and the safe versions its steps show."""
    pids = list(dict.fromkeys(pid for d in c["do"] for pid in d.get("versions", [])))
    safe = [{"id": pid, "name": VERSIONS[pid]["name"], "url": f"{SITE_URL}/versions/{pid}/",
             "json": f"{SITE_URL}/versions/{pid}.json", "checked": VERSIONS[pid]["checked"],
             "lines": [{k: l[k] for k in ("line", "latest", "released", "note") if k in l} for l in VERSIONS[pid]["lines"]],
             **({"older": VERSIONS[pid]["older"]} if VERSIONS[pid].get("older") else {})} for pid in pids]
    return {"url": f'{SITE_URL}/{c["slug"]}/', "json": f'{SITE_URL}/{c["slug"]}.json',
            "verdict_label": VERDICTS[c["verdict"]], "scare_label": scare_label(c["status"]["scare"]),
            **c, **({"safe_versions": safe} if safe else {})}


def index_row(c: dict) -> dict:
    s = c["status"]
    row = {k: c[k] for k in ("slug", "name", "cves", "product", "verdict") if k in c}
    row.update({"kind": c.get("kind", "vulnerability"), "verdict_label": badge_text(c), "tile_line": c["tile_line"], "scare": s["scare"],
                "scare_label": scare_label(s["scare"]), "exploit": s["exploit"], "attacks": s["attacks"],
                "kev": s["kev"]})
    row.update({k: c[k] for k in ("tldr", "ghsa", "also_in") if c.get(k)})
    if "no_login" in s:
        row["no_login"] = s["no_login"]
    row.update({k: c[k] for k in ("disclosed", "news", "updated") if c.get(k)})
    row.update({"url": f'{SITE_URL}/{c["slug"]}/', "json": f'{SITE_URL}/{c["slug"]}.json'})
    return row


def dump(rel: str, obj) -> None:
    out = OUT / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def write_data(all_c: list) -> None:
    by_update = sorted(all_c, key=lambda c: (c["updated"], c["slug"]), reverse=True)
    for c in all_c:
        dump(f'{c["slug"]}.json', page_data(c))
    for pid in VERSIONS:
        dump(f"versions/{pid}.json", version_data(pid, all_c))
    for wk in WEEKS:
        w = wk["week"]
        d = week_data(w, all_c)
        dump(f"week/{week_slug(w)}.json", {
            "week": w, "start": d["start"], "end": d["end"], "url": f"{SITE_URL}/week/{week_slug(w)}/", "intro": wk.get("intro", ""),
            "new": [index_row(c) for c in d["new"]],
            "changed": [{"date": dt, "slug": c["slug"], "name": c["name"], "text": t, "url": f'{SITE_URL}/{c["slug"]}/'} for dt, c, t in d["changed"]],
            "releases": [{"date": dt, "product": pid, "line": l["line"], "latest": l["latest"], "url": f"{SITE_URL}/versions/{pid}/"} for dt, pid, v, l in d["releases"]],
            "ahead": [{**e, "url": e["url"] if e["url"].startswith("http") else SITE_URL + e["url"]} for e in d["ahead"]],
        })
    dump("api/cves.json", {
        "site": SITE_URL, "updated": max(c["updated"] for c in all_c),
        "about": "Every page on tldrcve.com, newest update first. Each page's full data is at its json URL.",
        "verdicts": VERDICTS, "scare_labels": [z[1] for z in ZONES],
        "pages": [index_row(c) for c in by_update],
        "safe_versions": [{"id": pid, "name": v["name"], "checked": v["checked"], "url": f"{SITE_URL}/versions/{pid}/",
                           "json": f"{SITE_URL}/versions/{pid}.json"} for pid, v in VERSIONS.items()],
        "weeks": [{"week": w["week"], "url": f'{SITE_URL}/week/{week_slug(w["week"])}/', "json": f'{SITE_URL}/week/{week_slug(w["week"])}.json'}
                  for w in WEEKS],
    })

    def flat(s: str) -> str:  # one line, no markup: llms.txt is read as plain Markdown
        return re.sub(r"\[([^\]]+)\]\((/[a-z0-9/-]*)\)", r"\1", s).replace("\n", " ")

    lines = [
        "# tldrcve",
        "",
        "> The vulnerabilities people are talking about, in plain English: how scary each one is, whether you're "
        "affected, and what to do. Every claim cites a source.",
        "",
        "Verdicts: " + "; ".join(f"`{k}` = {v}" for k, v in VERDICTS.items()) + ". "
        "Scare level runs 0-4: " + ", ".join(f"{z[1]} below {z[0]}" for z in ZONES[:-1]) + f", then {ZONES[-1][1]}. "
        "In the JSON, `affected` lists conditions that must all be true, `cite` numbers are 1-based indexes into "
        "`sources`, and text uses `backticks` for code and [label](/path/) for links to this site. "
        "Every CVE or GHSA ID also works as a URL, e.g. https://tldrcve.com/CVE-2026-125396 redirects to its page.",
        "",
        "## Data",
        "",
        f"- [All pages as JSON]({SITE_URL}/api/cves.json): verdict, scare level, exploit, attacks and KEV status for every page, with links to each page's JSON",
        f"- Each page as JSON: add `.json` to the page path, e.g. {SITE_URL}/upload2shell.json",
        f"- Safe versions as JSON: {SITE_URL}/versions/<product>.json, e.g. {SITE_URL}/versions/ghostscript.json",
        f"- RSS feeds: [CVEs]({SITE_URL}/feed.xml), [incidents]({SITE_URL}/incidents/feed.xml) and "
        f"[both]({SITE_URL}/all/feed.xml). Each has new pages (TL;DR and details) and material updates (what changed, then the "
        "current TL;DR; wording and source fixes are left out), each with its preview image and categories "
        "(type, verdict, scare, exploit, attacks, CISA KEV, product, CVE) for filtering; the CVE and combined feeds also "
        "carry the weekly review",
        f"- JSON Feed: the same items as JSON Feed 1.1 at feed.json next to each feed.xml; `_tldrcve` on each item holds the raw "
        "verdict, scare, exploit, attacks, KEV dates, product and CVEs, plus a link to the page's JSON",
        f"- [Weekly review]({SITE_URL}/week/): each week's new pages, changes and the dates coming up; JSON at /week/<yyyy>-w<nn>.json",
        "",
        "## Pages",
        "",
    ]
    for c in by_update:
        ids = ", ".join(c["cves"][:3]) + (f" +{len(c['cves']) - 3} more" if len(c["cves"]) > 3 else "")
        lines.append(f'- [{c["name"]}]({SITE_URL}/{c["slug"]}/): {product_full(c)}'
                     + (f" ({ids})" if ids else "") + f'. {VERDICTS[c["verdict"]]} · {scare_label(c["status"]["scare"])}. '
                     + flat(c["tile_line"]) + f' Updated {c["updated"]}.')
    if WEEKS:
        lines += ["", "## Weekly reviews", "", f"- [All weeks]({SITE_URL}/week/): new pages, changes and the dates coming up, week by week"]
        for wk in reversed(WEEKS):
            lines.append(f'- [{week_title(wk["week"])}]({SITE_URL}/week/{week_slug(wk["week"])}/): {week_label(wk["week"])}')
    lines += ["", "## Safe versions", "", f"- [All products]({SITE_URL}/versions/): newest safe release per product line"]
    for pid, v in VERSIONS.items():
        latest = ", ".join(l["latest"] for l in v["lines"])
        lines.append(f'- [{v["name"]}]({SITE_URL}/versions/{pid}/): {latest} (checked {v["checked"]})')
    lines += ["", "## About", "",
              f"- [Home]({SITE_URL}/): latest pages",
              f"- [All CVEs]({SITE_URL}/cves/): every CVE page, filterable by product and date",
              f"- [Incidents]({SITE_URL}/incidents/): attacks that already happened: how bad, who says so, what to clean up",
              f"- [How we rate]({SITE_URL}/how-we-rate/): what the verdicts and scare levels mean",
              f"- [Source on GitHub]({REPO_URL}): content files, corrections welcome", ""]
    (OUT / "llms.txt").write_text("\n".join(lines))


def write_host_files(public: bool) -> None:
    """Cloudflare reads _headers; robots.txt keeps crawlers out of non-public builds."""
    headers = [
        "/*",
        f"  Content-Security-Policy: {CSP}",
        "  Strict-Transport-Security: max-age=31536000; includeSubDomains",
        "  X-Content-Type-Options: nosniff",
        "  Referrer-Policy: strict-origin-when-cross-origin",
        "  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()",
        "  Cross-Origin-Opener-Policy: same-origin",
    ]
    if not public:
        headers.append("  X-Robots-Tag: noindex, nofollow")
    # Only fingerprinted files are cached forever. Everything else (link-preview images, plain copies)
    # keeps a short cache, so a request that lands mid-deploy can't pin an old file for a year.
    headers += ["", "/assets/*", "  Cache-Control: public, max-age=3600",
                "", "/assets/v/*", "  ! Cache-Control", "  Cache-Control: public, max-age=31536000, immutable",
                "", "/*.json", "  Access-Control-Allow-Origin: *",
                "", "/llms.txt", "  Access-Control-Allow-Origin: *", ""]
    (OUT / "_headers").write_text("\n".join(headers))
    robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n" if public else "User-agent: *\nDisallow: /\n"
    (OUT / "robots.txt").write_text(robots)


def not_found_page() -> str:
    body = """  <main class="wrap prose-page">
    <header class="page-head">
      <h1>Nothing here</h1>
      <p data-notfound>That page doesn't exist, or it moved. Try <a href="/cves/">all CVEs</a> or the <a href="/">homepage</a>.</p>
    </header>
  </main>
"""
    return page("Not found · tldrcve", "Page not found.", body, path="404")


def freeze_week(w: str, all_c: list) -> None:
    """Write a finished week's computed contents into its weeks/ file, so the page stops changing."""
    path = WEEKS_DIR / f"{week_slug(w)}.json"
    wk = json.loads(path.read_text())
    if wk.get("snapshot"):
        sys.exit(f"{w} is already frozen")
    if week_bounds(w)[1] >= date.today():
        sys.exit(f"{w} isn't over yet (ends {week_bounds(w)[1]})")
    d = week_data(w, all_c)
    wk["snapshot"] = {"start": d["start"], "end": d["end"], "new": [c["slug"] for c in d["new"]],
                      "changed": [[dt, c["slug"], t] for dt, c, t in d["changed"]],
                      "releases": [[dt, pid, v["name"], l["line"], l["latest"]] for dt, pid, v, l in d["releases"]],
                      "ahead": d["ahead"]}
    path.write_text(json.dumps(wk, indent=2, ensure_ascii=False) + "\n")
    print(f"froze {w} in {path.relative_to(ROOT)}")


def main() -> None:
    all_c = [json.loads(p.read_text()) for p in sorted(CONTENT.glob("*.json"))]
    PAGES.update({c["slug"]: c for c in all_c})
    missing = [c["slug"] for c in all_c if not c.get("tldr")]
    if missing:
        sys.exit(f"every page needs a tldr (the TL;DR panel, meta description, feed item and X post): {', '.join(missing)}")
    if "--freeze-week" in sys.argv:
        i = sys.argv.index("--freeze-week")
        if i + 1 >= len(sys.argv) or not WEEK_RE.match(sys.argv[i + 1]):
            sys.exit("usage: python3 build.py --freeze-week 2026-W47")
        return freeze_week(sys.argv[i + 1], all_c)
    warnings = editor_checks(all_c) + versions_checks(all_c)
    slugs = {c["slug"] for c in all_c}
    for c in all_c:
        for b in c.get("bugs", []):
            if b.get("page"):
                if b["page"] not in slugs:
                    warnings.append(f'{c["slug"]}.bugs: {b["cve"]} links to missing page /{b["page"]}/')
                ROUNDUP_OF[b["page"]] = c
    for wk in WEEKS:  # a note, not a warning: an unfrozen week must never block a deploy
        if WEEK_RE.match(wk.get("week", "")) and not wk.get("snapshot") and week_bounds(wk["week"])[1] < date.today():
            print(f"note: {wk['week']} is over; freeze it (on Monday) with python3 build.py --freeze-week {wk['week']}")
    watch_warnings, watch_notes = watch_checks(all_c)
    warnings += watch_warnings
    for note in watch_notes:
        print(f"note: {note}")
    missing_cards, stale_cards = card_checks(all_c)
    warnings += missing_cards  # every page needs its own card, right away
    for note in stale_cards:  # an outdated card blocks a deploy; elsewhere it's a note
        if "--public" in sys.argv:
            warnings.append(note)
        else:
            print(f"note: {note}")
    for w in warnings:
        print(f"warning: {w}")
    if warnings and "--strict" in sys.argv:
        sys.exit(f"{len(warnings)} warning(s); --strict build failed")

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ASSETS, OUT / "assets")
    write_fingerprinted()
    shutil.copyfile(ASSETS / "icons" / "favicon.ico", OUT / "favicon.ico")  # browsers ask for /favicon.ico
    pages = {"index.html": home(all_c), "cves/index.html": cves_page(all_c), "how-we-rate/index.html": how_page(),
             "incidents/index.html": incidents_page(all_c),
             "404.html": not_found_page(), "versions/index.html": versions_index(all_c)}
    pages.update({f"versions/{pid}/index.html": versions_page(v, all_c) for pid, v in VERSIONS.items()})
    pages.update({f'{c["slug"]}/index.html': brief(c) for c in all_c})
    if WEEKS:
        pages["week/index.html"] = weeks_index(all_c)
        pages.update({f'week/{week_slug(w["week"])}/index.html': week_page(w, all_c) for w in WEEKS})
    for rel, content in pages.items():
        out = OUT / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
    public = "--public" in sys.argv
    write_host_files(public)
    write_sitemap(all_c)
    write_redirects(all_c)
    write_feeds(all_c)
    write_data(all_c)
    (OUT / "build.txt").write_text(os.environ.get("TLDRCVE_BUILD_ID", "local"))  # lets CI see when a deploy is live
    print(f"{'PUBLIC' if public else 'private (noindex)'} build:", end=" ")
    print(f"built {len(all_c)} briefs + home, all CVEs, how we rate -> {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
