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
from datetime import date
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

# Scare-o-meter zones, 0–4.
ZONES = [
    (1, "Shrug", "Real, but not worth losing sleep over."),
    (2, "Keep an eye on it", "Patch on schedule. Watch for news."),
    (3, "Check today", "Find out if you're affected. If you are, patch."),
    (4.01, "Drop everything", "Attackers are already on it. Patch now."),
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
    """Escape, then turn `backticks` into <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(s, quote=False))


def nice_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def zone(scare: float):
    for limit, label, hint in ZONES:
        if scare < limit:
            return label, hint
    return ZONES[-1][1], ZONES[-1][2]


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


def page(title: str, description: str, body: str, current: str = "", path: str = "") -> str:
    seo = social_tags(title, description, path)
    cur = {k: ' aria-current="page"' if k == current else "" for k in ("cves", "versions", "how")}
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
  <link rel="alternate" type="application/rss+xml" title="tldrcve updates" href="/feed.xml">
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
        <a href="/versions/"{cur["versions"]}>Safe versions</a>
        <a href="/how-we-rate/"{cur["how"]}>How we rate</a>
      </nav>
    </div>
  </header>
{body}
  <footer class="site-footer">
    <div class="wrap">
      <p class="follow">Follow <a href="https://x.com/{X_HANDLE}">@{X_HANDLE}</a> on X for live updates, or subscribe to the <a href="/feed.xml">RSS feed</a>.</p>
      <p>Every claim is sourced. Wrong or out of date? Tell us on X. Made by <a href="https://x.com/{AUTHOR_HANDLE}">@{AUTHOR_HANDLE}</a>.</p>
    </div>
  </footer>
</body>
</html>
"""


# ---------- Scare-o-meter ----------

def _xy(r: float, deg: float):
    a = math.radians(deg)
    return 100 + r * math.cos(a), 100 - r * math.sin(a)


def gauge(scare: float) -> str:
    r = 78
    arcs = []
    for i, color in enumerate(METER_COLORS):
        x0, y0 = _xy(r, 180 - 45 * i - 1.5)
        x1, y1 = _xy(r, 180 - 45 * (i + 1) + 1.5)
        arcs.append(f'<path d="M {x0:.2f} {y0:.2f} A {r} {r} 0 0 1 {x1:.2f} {y1:.2f}" stroke="{color}"/>')
    nx, ny = _xy(64, 180 - 45 * max(0.0, min(4.0, scare)))
    label, hint = zone(scare)
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

    if "no_login" in s:
        rows.append(("no_login",) + (("yes", "Works without logging in") if s["no_login"]
                    else ("no", f"Needs {s.get('needs', 'a login')} first")))
    rows.append(("exploit",) + {
        "public": ("yes", "Public exploit code is out"),
        "demonstrated": ("part", "Shown working, code not public"),
        "none": ("no", "No public exploit"),
    }[s["exploit"]])
    rows.append(("attacks",) + (("yes", "Attacks seen in the wild") if s["attacks"] == "seen" else ("no", "No attacks seen yet")))
    kev = s.get("kev")
    if kev:
        due = date.fromisoformat(kev["due"])
        when = f"fix by {nice_date(kev['due'])}" if due >= date.today() else f"since {nice_date(kev['added'])}"
        rows.append(("kev", "yes", f"On CISA's exploited list ({when})"))
    elif s.get("cisa_alert"):
        rows.append(("kev", "part", "CISA says patch now (not on its exploited list)"))
    else:
        rows.append(("kev", "no", "Not on CISA's exploited list"))

    cites = c.get("status_cite", {})
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
    post = quote(f"{c['name']} ({', '.join(c['cves'])}): {VERDICTS[c['verdict']]}. Are you affected?")
    x = f"https://x.com/intent/post?text={post}&url={quote(url, safe='')}"
    li = f"https://www.linkedin.com/sharing/share-offsite/?url={quote(url, safe='')}"
    return f"""    <div class="toolbar">
      <a class="back" href="/cves/">{ICONS["back"]}All CVEs</a>
      <div class="share" role="group" aria-label="Share">
        <button class="icon-btn" type="button" data-copy="tldr-text" aria-label="Copy summary for Slack" data-tip="Copy summary">{ICONS["copy"]}</button>
        <button class="icon-btn" type="button" data-copy-link="{html.escape(url)}" aria-label="Copy link" data-tip="Copy link">{ICONS["link"]}</button>
        <a class="icon-btn" href="{html.escape(x)}" target="_blank" rel="noopener" aria-label="Post on X" data-tip="Post on X">{ICONS["x"]}</a>
        <a class="icon-btn" href="{html.escape(li)}" target="_blank" rel="noopener" aria-label="Share on LinkedIn" data-tip="LinkedIn">{ICONS["in"]}</a>
      </div>
      <p id="tldr-text" class="visually-hidden">{html.escape(c["slack"])} {html.escape(url)}</p>
    </div>"""


def brief(c: dict) -> str:
    v = c["verdict"]
    s = c["status"]
    kicker = [product_full(c), *c["cves"]]
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
    body = f"""  <main class="wrap brief">
{toolbar(c)}

    <header class="brief-head">
      <p class="kicker">{html.escape(" · ".join(kicker))}</p>
      <h1>{html.escape(c["name"])}</h1>
      <p class="verdict-line"><span class="verdict verdict--{v} verdict--lg">{VERDICTS[v]}</span><span>{text(c["tile_line"])}</span></p>
      <p class="summary">{text(c["summary"])}</p>
    </header>

    <section class="pane" aria-labelledby="h-scare">
      <div class="pane__head"><h2 id="h-scare">How scary is it?</h2><span class="pane__meta">updated {nice_date(c["updated"])}</span></div>
      <div class="scare">
        {checklist(c)}
        {gauge(s["scare"])}
      </div>
    </section>

    <section class="pane" aria-labelledby="h-affected" data-folds>
      <div class="pane__head">
        <h2 id="h-affected">Are you affected? <span class="pane__sub">only if <strong>all</strong> are true</span></h2>
        <button class="link-btn" type="button" data-expand-all>Expand all</button>
      </div>
{fold_items(c["affected"])}
    </section>

    <section class="pane" aria-labelledby="h-do" data-folds>
      <div class="pane__head">
        <h2 id="h-do">What to do</h2>
        <button class="link-btn" type="button" data-expand-all>Expand all</button>
      </div>
{fold_items(c["do"])}
    </section>

    <p class="disclaimer">This page shows you how to check. It can't tell you you're safe.</p>
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
    title = f'{c["name"]} ({", ".join(c["cves"])}) in plain English · tldrcve'
    return page(title, c["summary"], body, path=f"/{c['slug']}/")


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
        <span class="vbug__meta">{html.escape(", ".join(c["cves"]) or "No CVE yet")} · {nice_date(c["disclosed"])}</span>
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
    return page(f'Latest safe {v["name"]} versions · tldrcve', v["about"], body, current="versions", path=f"/versions/{pid}/")


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


# ---------- Home ----------

LATEST_COUNT = 6
SEARCH_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'


def news_date(c: dict) -> str:
    """When it hit the news: an old bug can become news later (new attacks, a CISA listing)."""
    return c.get("news", c["disclosed"])


def tile(c: dict) -> str:
    v = c["verdict"]
    return f"""      <li>
        <a class="tile" href="/{c["slug"]}/">
          <span class="tile__meta"><span class="tile__product">{html.escape(product_short(c))}</span><span>· {nice_date(news_date(c))}</span></span>
          <span class="tile__name">{html.escape(c["name"])}</span>
          <span class="tile__line">{text(c["tile_line"])}</span>
          <span class="tile__foot"><span class="verdict verdict--{v}">{VERDICTS[v]}</span>{mini_meter(c["status"]["scare"])}</span>
        </a>
      </li>"""


def zones_list() -> str:
    rows = "\n".join(
        f'        <li>{mini_meter(i + 0.5)}<strong>{label}</strong><span>{hint}</span></li>'
        for i, (_, label, hint) in enumerate(ZONES)
    )
    return f'      <ul class="zones">\n{rows}\n      </ul>'


def home(all_c: list) -> str:
    latest = sorted(all_c, key=news_date, reverse=True)[:LATEST_COUNT]
    body = f"""  <main class="wrap home">
    <section class="hero">
      <h1>CVEs in plain English</h1>
      <p class="hero__lede">The vulnerabilities everyone's panicking about.<br>Are you affected, and what should you do?</p>
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
{chr(10).join(tile(c) for c in latest)}
    </ul>

    <section class="pane rate">
      <div class="pane__head"><h2>The scare-o-meter</h2><a class="more-link" href="/how-we-rate/">How we rate →</a></div>
{zones_list()}
    </section>
  </main>
"""
    return page("tldrcve: CVEs in plain English",
                "The vulnerabilities everyone's talking about, in plain English: are you affected, and what to do.",
                body, current="home", path="/")


# ---------- All CVEs ----------

def cves_page(all_c: list) -> str:
    ordered = sorted(all_c, key=lambda c: c["status"]["scare"], reverse=True)
    rows = []
    for c in ordered:
        v = c["verdict"]
        search = " ".join([c["name"], product_full(c), *c["cves"], *c.get("ghsa", []), *c.get("aliases", [])]).lower()
        rows.append(
            f"""      <li class="row" data-search="{html.escape(search)}" data-scare="{c["status"]["scare"]}" data-disclosed="{c["disclosed"]}">
        <a href="/{c["slug"]}/">
          <span class="row__meter">{mini_meter(c["status"]["scare"])}</span>
          <span class="row__main">
            <span class="row__name">{html.escape(c["name"])}</span>
            <span class="row__meta">{html.escape(product_short(c))} · {html.escape(", ".join(c["cves"]))}</span>
          </span>
          <span class="row__line">{text(c["tile_line"])}</span>
          <span class="row__verdict"><span class="verdict verdict--{v}">{VERDICTS[v]}</span></span>
          <time class="row__date" datetime="{c["disclosed"]}">{nice_date(c["disclosed"])}</time>
        </a>
      </li>"""
        )
    body = f"""  <main class="wrap list-page" data-list>
    <header class="page-head">
      <h1>All CVEs</h1>
      <p>{len(all_c)} vulnerabilities people are actually asking about. Nothing else.</p>
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


# ---------- How we rate ----------

def how_page() -> str:
    body = f"""  <main class="wrap prose-page">
    <header class="page-head">
      <h1>How we rate</h1>
      <p>Every page answers three questions:<br>How scary is it, are you affected, and what should you do.</p>
    </header>

    <section class="pane">
      <div class="pane__head"><h2>The scare-o-meter</h2></div>
{zones_list()}
      <div class="pane__body">
        <p>What moves the needle, biggest first:<br><strong>Attacks seen in the wild</strong>, a listing on <strong>CISA's exploited list</strong>, <strong>public exploit code</strong>, whether it <strong>works without logging in</strong>, and <strong>how common</strong> the affected setup is.<br>A scary CVSS score on its own doesn't move it.</p>
      </div>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>Verdicts</h2></div>
      <dl class="defs">
        <dt><span class="verdict verdict--now">Patch now</span></dt><dd>Working exploit or attacks seen, and common setups are exposed.</dd>
        <dt><span class="verdict verdict--if">Patch now if…</span></dt><dd>Serious, but only under conditions we list. Each page shows you how to check them.</dd>
        <dt><span class="verdict verdict--cycle">Next cycle</span></dt><dd>Real, but hard to reach or low impact. Patch on your normal schedule.</dd>
      </dl>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>The checklist</h2></div>
      <dl class="defs">
        <dt>Works without logging in</dt><dd>The attacker needs no account, password or certificate.</dd>
        <dt>Public exploit code is out</dt><dd>Working code anyone can download. A blog post or video doesn't count, and neither do the fake exploits that show up after every big CVE.</dd>
        <dt>Shown working</dt><dd>A researcher demonstrated it, but hasn't published the code.</dd>
        <dt>Attacks seen in the wild</dt><dd>A credible report from the vendor, CISA or a named security team.</dd>
        <dt>On CISA's exploited list</dt><dd>Listed in CISA's <a href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog">Known Exploited Vulnerabilities</a> catalog. The fix-by date is the US federal deadline, which is a good default for everyone else.</dd>
      </dl>
    </section>

    <section class="pane">
      <div class="pane__head"><h2>House rules</h2></div>
      <ul class="rules">
        <li><strong>Every claim has a source.</strong> Click the little numbers.</li>
        <li><strong>Every change is logged.</strong> Facts move fast in the first days. Each page has a changelog.</li>
        <li><strong>We show you how to check.</strong> We never tell you you're safe.</li>
        <li><strong>We skip the noise.</strong> We only cover the CVEs people are actually asking about.</li>
        <li><strong>We get things wrong sometimes.</strong> Tell us on X (<a href="https://x.com/{X_HANDLE}">@{X_HANDLE}</a>) and we'll fix it, in the open.</li>
      </ul>
    </section>
  </main>
"""
    return page("How we rate · tldrcve", "How tldrcve decides how scary a CVE is, and what each label means.",
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
    card = (path or "/").strip("/") or "default"
    if not (ASSETS / "og" / f"{card}.png").exists():
        card = "default"
    img = f"{SITE_URL}/assets/og/{card}.png?v={asset_version(f'og/{card}.png')}"
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
    urls = [("/", newest), ("/cves/", newest), ("/versions/", newest), ("/how-we-rate/", newest)]
    urls += [(f"/versions/{pid}/", v["checked"]) for pid, v in sorted(VERSIONS.items())]
    urls += [(f'/{c["slug"]}/', c["updated"]) for c in sorted(all_c, key=lambda c: c["slug"])]
    body = "\n".join(f"  <url><loc>{SITE_URL}{p}</loc><lastmod>{d}</lastmod></url>" for p, d in urls)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>\n")


FEED_ITEMS = 60


def write_feed(all_c: list) -> None:
    """RSS 2.0: one item per changelog entry across all pages, newest first."""
    from email.utils import format_datetime
    from datetime import datetime, timezone
    entries = sorted(((ch["date"], -i, c, ch["text"]) for c in all_c for i, ch in enumerate(c["changes"])),
                     key=lambda e: (e[0], e[1]), reverse=True)[:FEED_ITEMS]

    def rfc822(d):
        return format_datetime(datetime.fromisoformat(d).replace(hour=12, tzinfo=timezone.utc))

    items = []
    for d, neg_i, c, t in entries:
        url = f'{SITE_URL}/{c["slug"]}/'
        verb = "New" if t == "Published." else "Update"
        title = f'{verb}: {c["name"]} ({", ".join(c["cves"]) or "no CVE yet"})'
        desc = c["summary"] if t == "Published." else t
        items.append(f"""    <item>
      <title>{html.escape(title)}</title>
      <link>{url}</link>
      <guid isPermaLink="false">{c["slug"]}-{d}-{-neg_i}</guid>
      <pubDate>{rfc822(d)}</pubDate>
      <description>{html.escape(desc.replace("`", ""))} Verdict: {html.escape(VERDICTS[c["verdict"]])}</description>
    </item>""")
    newest = entries[0][0] if entries else date.today().isoformat()
    (OUT / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>tldrcve</title>
    <link>{SITE_URL}/</link>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>The vulnerabilities everyone's talking about, in plain English. New pages and updates.</description>
    <language>en</language>
    <lastBuildDate>{rfc822(newest)}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
""")


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
                "", "/assets/v/*", "  ! Cache-Control", "  Cache-Control: public, max-age=31536000, immutable", ""]
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


def main() -> None:
    all_c = [json.loads(p.read_text()) for p in sorted(CONTENT.glob("*.json"))]
    warnings = editor_checks(all_c) + versions_checks(all_c)
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
             "404.html": not_found_page(), "versions/index.html": versions_index(all_c)}
    pages.update({f"versions/{pid}/index.html": versions_page(v, all_c) for pid, v in VERSIONS.items()})
    pages.update({f'{c["slug"]}/index.html': brief(c) for c in all_c})
    for rel, content in pages.items():
        out = OUT / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
    public = "--public" in sys.argv
    write_host_files(public)
    write_sitemap(all_c)
    write_redirects(all_c)
    write_feed(all_c)
    (OUT / "build.txt").write_text(os.environ.get("TLDRCVE_BUILD_ID", "local"))  # lets CI see when a deploy is live
    print(f"{'PUBLIC' if public else 'private (noindex)'} build:", end=" ")
    print(f"built {len(all_c)} briefs + home, all CVEs, how we rate -> {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
