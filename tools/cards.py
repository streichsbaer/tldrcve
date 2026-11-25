"""Render the link-preview images (1200x630) that X, Slack and LinkedIn show for each page.

  python3 tools/cards.py            # render every card that is missing or out of date
  python3 tools/cards.py --all      # render them all again

Writes assets/og/<slug>.png, assets/og/default.png and assets/og/cards.json (what each card was drawn from).
Needs a desktop browser for the screenshots: Google Chrome, Chromium, Firefox or Zen.
Set TLDRCVE_BROWSER to its executable if it isn't found. The build itself never needs a browser.
"""
import hashlib, html, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build  # noqa: E402  (reuses the site's own verdict labels and scare zones)

OUT = ROOT / "assets" / "og"
W, H = 1200, 630
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@800'
         '&family=Instrument+Sans:wght@500;700&family=IBM+Plex+Mono:wght@600&display=block">')
BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    "/Applications/Zen.app/Contents/MacOS/zen",
    "google-chrome", "chromium", "chromium-browser", "firefox",
]
VERDICT_COLORS = {"now": ("#b3261e", "#ffe1dc"), "if": ("#8a5a00", "#fff0c2"),
                  "cycle": ("#22663f", "#dff3e4"), "watch": ("#4b5563", "#eceef1")}
METER = ["#8fd19e", "#ffd84d", "#ff9f43", "#ff5e57"]

CSS = """
*{box-sizing:border-box}
html,body{margin:0;width:1200px;height:630px;overflow:hidden;background:#fbf7ee;color:#17150f}
body{padding:56px 72px 130px;display:flex;flex-direction:column;gap:34px;font-family:"Instrument Sans",sans-serif}
/* X lays the page title over the bottom-left of the image, so the bottom 130px stays empty */
.top{display:flex;align-items:center;justify-content:space-between}
.mark{display:flex;align-items:center;gap:14px}
.tldr{font:800 50px/1 "Schibsted Grotesk";letter-spacing:-0.04em;background:#ffe066;padding:5px 14px 10px;border-radius:10px;
  transform:rotate(-3deg);border:3px solid #17150f;box-shadow:5px 5px 0 #17150f}
.cve{font:600 32px/1 "IBM Plex Mono";letter-spacing:0.06em;color:#e4572e}
.url{font:600 24px/1 "IBM Plex Mono";color:#7d7567}
.main{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:18px}
h1{font:800 96px/1 "Schibsted Grotesk";letter-spacing:-0.035em;margin:0;white-space:nowrap}
.ids{font:600 28px/1 "IBM Plex Mono";color:#4a443a}
.line{font:500 36px/1.3 "Instrument Sans";color:#4a443a;margin:0}
.bottom{display:flex;align-items:center;gap:22px}
.verdict{font:700 30px/1 "Instrument Sans";padding:14px 24px;border-radius:999px;display:flex;align-items:center;gap:12px}
.verdict::before{content:"";width:16px;height:16px;border-radius:50%;background:currentColor}
.meter{display:flex;gap:6px}
.meter i{width:44px;height:20px;border-radius:5px;border:2.5px solid #17150f;background:#fff}
.zone{font:700 30px/1 "Instrument Sans"}
.tag{font:500 46px/1.3 "Instrument Sans";color:#4a443a;margin:0;max-width:960px}
.tag b{color:#17150f}
.kick{font:600 28px/1 "IBM Plex Mono";color:#7d7567;text-transform:uppercase;letter-spacing:0.06em}
.chips{display:flex;flex-wrap:wrap;gap:12px;max-width:1056px}
.chip{display:inline-flex;border:2.5px solid #17150f;border-radius:10px;overflow:hidden;font:600 28px/1 "IBM Plex Mono"}
.chip span{padding:10px 12px;background:#f3eee3;color:#4a443a;font:700 26px/1 "Instrument Sans"}
.chip b{padding:10px 14px;background:#dff3e4;color:#22663f}
.chip.nofix b{background:#ffe1dc;color:#b3261e;font-family:"Instrument Sans"}
.more{font:600 28px/1 "IBM Plex Mono";color:#7d7567;align-self:center}
"""


def header(right):
    return (f'<div class="top"><div class="mark"><span class="tldr">tl;dr</span><span class="cve">CVE</span></div>'
            f'<span class="url">{html.escape(right)}</span></div>')


def page_card(c):
    fg, bg = ("#5b3fa0", "#ece6f8") if build.is_incident(c) else VERDICT_COLORS[c["verdict"]]
    scare = c["status"]["scare"]
    label, _ = build.zone_for(c)
    filled = next((i + 1 for i, (limit, _, _) in enumerate(build.ZONES) if scare < limit), len(build.ZONES))
    meter = "".join(f'<i style="background:{METER[i] if i < filled else "#fff"}"></i>' for i in range(4))
    if c.get("bugs"):  # a release roundup: count every bug instead of listing IDs
        ids = f"{build.cve_list(c)} · {build.nice_date(c['disclosed'])}"
    else:
        ids = " · ".join(c["cves"][:2]) + (f" +{len(c['cves']) - 2} more" if len(c["cves"]) > 2 else "") or "No CVE yet"
    return f"""{header("tldrcve.com/" + c["slug"])}
<div class="main"><div class="ids">{html.escape(ids)}</div><h1>{html.escape(c["name"])}</h1>
<p class="line">{html.escape(c["tile_line"])}</p></div>
<div class="bottom"><span class="verdict" style="color:{fg};background:{bg}">{html.escape(build.badge_text(c))}</span>
<span class="meter">{meter}</span><span class="zone">{html.escape(label)}</span></div>"""


def count(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def default_card(n_cve, n_inc):
    return f"""{header("tldrcve.com")}
<div class="main"><p class="tag">The vulnerabilities and attacks everyone's talking about, <b>in plain English.</b>
How scary is it, are you affected, and what to do.</p>
<p class="line">{count(n_cve, "CVE")} and {count(n_inc, "incident")} covered so far.</p></div>"""


def text_card(right, kicker, title, line):
    return f"""{header(right)}
<div class="main">{f'<div class="kick">{html.escape(kicker)}</div>' if kicker else ""}<h1>{html.escape(title)}</h1>
<p class="line">{html.escape(line)}</p></div>"""


def product_card(v, n_bugs):
    lines = [(l["line"], l["latest"], False) for l in v["lines"]] + [(u["line"], "No fix", True) for u in v.get("unfixed", [])]
    fixed = [x for x in lines if not x[2]]
    nofix = [x for x in lines if x[2]]
    shown = fixed[:4] + nofix[:1] if nofix else fixed[:5]
    chips = "".join(f'<span class="chip{" nofix" if nf else ""}"><span>{html.escape(a)}</span><b>{html.escape(b)}</b></span>'
                    for a, b, nf in shown)
    if len(lines) > len(shown):
        chips += f'<span class="more">+{len(lines) - len(shown)} more</span>'
    return f"""{header("tldrcve.com/versions/" + v["id"])}
<div class="main"><div class="kick">Latest safe versions</div><h1{h1_size(v["name"])}>{html.escape(v["name"])}</h1>
<div class="chips">{chips}</div></div>"""


def h1_size(name: str) -> str:
    """Long product names get a smaller title so they fit on one line (about 0.56 em per character at 96px)."""
    size = min(96, int((W - 144) / (0.56 * len(name))))
    return "" if size == 96 else f' style="font-size:{size}px"'


def find_browser():
    for b in [os.environ.get("TLDRCVE_BROWSER")] + BROWSERS:
        if b and (Path(b).exists() or shutil.which(b)):
            return b
    sys.exit("No browser found. Set TLDRCVE_BROWSER to Chrome, Chromium, Firefox or Zen.")


def shoot(browser, html_file, png, profile):
    if "chrom" in browser.lower():
        cmd = [browser, "--headless=new", "--hide-scrollbars", "--force-device-scale-factor=1",
               f"--window-size={W},{H}", f"--screenshot={png}", "--virtual-time-budget=5000", html_file.as_uri()]
    else:
        cmd = [browser, "--headless", "-no-remote", "--profile", profile,
               f"--window-size={W},{H}", "--screenshot", str(png), html_file.as_uri()]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
    if not png.exists() or png.stat().st_size == 0:
        sys.exit(f"The browser didn't write {png}")


def documents(all_c):
    n_inc = sum(1 for c in all_c if build.is_incident(c))
    n_cve = len(all_c) - n_inc
    cards = {"default": default_card(n_cve, n_inc), **{c["slug"]: page_card(c) for c in all_c}}
    talked = "The ones people are actually talking about, in plain English."
    cards["cves"] = text_card("tldrcve.com/cves", None, count(n_cve, "CVE"), talked)
    cards["incidents"] = text_card("tldrcve.com/incidents", None, count(n_inc, "incident"), talked)
    cards["how-we-rate"] = text_card("tldrcve.com/how-we-rate", "How we rate", "The scare-o-meter",
                                     "Attacks, exploits and exposure count. A scary CVSS score alone doesn't.")
    cards["versions"] = text_card("tldrcve.com/versions", "Safe versions", "Latest safe versions",
                                  "The newest release on each line, with every bug we cover fixed.")
    for pid, v in build.VERSIONS.items():
        cards[f"versions/{pid}"] = product_card(v, len(build.product_pages(pid, all_c)))
    if build.WEEKS:
        cards["week"] = text_card("tldrcve.com/week", "Weekly review", "Every week",
                                  "New pages, what changed, and the patch days coming up.")
    for wk in build.WEEKS:
        w = wk["week"]
        d = build.week_data(w, all_c)
        cards[f"week/{build.week_slug(w)}"] = text_card(f"tldrcve.com/week/{build.week_slug(w)}", build.week_title(w),
                                                        build.week_label(w),
                                                        f'{len(d["new"])} new, {len({c["slug"] for _, c, _ in d["changed"]})} updated, {len(d["ahead"])} dates coming up.')
    return {slug: f'<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>{CSS}</style></head><body>{body}</body></html>'
            for slug, body in cards.items()}


def expected_keys(all_c):
    """What each card should be drawn from right now. build.py compares this with cards.json."""
    return {slug: hashlib.sha256(doc.encode()).hexdigest()[:16] for slug, doc in documents(all_c).items()}


def main():
    all_c = [json.loads(f.read_text()) for f in sorted((ROOT / "content").glob("*.json"))]
    cards = documents(all_c)
    keys = expected_keys(all_c)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_file = OUT / "cards.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    browser = find_browser()
    done = 0
    with tempfile.TemporaryDirectory() as tmp:
        for slug, doc in cards.items():
            key = keys[slug]
            png = OUT / f"{slug}.png"
            if "--all" not in sys.argv and manifest.get(slug) == key and png.exists():
                continue
            png.parent.mkdir(parents=True, exist_ok=True)
            src = Path(tmp) / f"{slug.replace('/', '__')}.html"
            src.write_text(doc)
            png.unlink(missing_ok=True)
            shoot(browser, src, png, tmp)
            manifest[slug] = key
            done += 1
            print(f"rendered {png.relative_to(ROOT)}")
    for slug in set(manifest) - set(cards):  # pages that were removed
        manifest.pop(slug)
        (OUT / f"{slug}.png").unlink(missing_ok=True)
    manifest_file.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    print(f"{done} card(s) rendered, {len(cards) - done} already up to date")


if __name__ == "__main__":
    main()
