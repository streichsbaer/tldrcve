"""Check the live site after a deploy: every page in the sitemap loads, has its own link-preview card,
and the card is a 1200x630 PNG. Also checks the favicon, RSS and JSON feeds, redirects for every CVE/GHSA ID, and the
agent files: /llms.txt, /api/cves.json and every page's and product's JSON.

  python3 tools/check_live.py                 # checks https://tldrcve.com
  python3 tools/check_live.py http://localhost:8787

Exits non-zero if anything is wrong. Python standard library only.
"""
import json, re, struct, sys, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://tldrcve.com").rstrip("/")
UA = {"User-Agent": "Twitterbot/1.0"}  # the preview crawler's view of the page


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(url, follow=True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def check_data(urls):
    """llms.txt and every JSON file exist, parse, match the sitemap, and can be read from other sites (CORS)."""
    problems = []
    slugs = sorted(json.loads(f.read_text())["slug"] for f in (ROOT / "content").glob("*.json"))
    products = sorted(f.stem for f in (ROOT / "versions").glob("*.json"))
    status, headers, body = get(f"{BASE}/llms.txt")
    llms = body.decode(errors="replace")
    if status != 200:
        problems.append(f"/llms.txt: HTTP {status}")
    else:
        if headers.get("Access-Control-Allow-Origin") != "*":
            problems.append("/llms.txt: no Access-Control-Allow-Origin: *")
        missing = [u for u in urls if f"https://tldrcve.com{u})" not in llms]
        if missing:
            problems.append(f"/llms.txt: no link to {', '.join(missing[:5])}")
    status, headers, body = get(f"{BASE}/api/cves.json")
    try:
        index = json.loads(body) if status == 200 else None
    except ValueError:
        index = None
    if not index:
        problems.append(f"/api/cves.json: HTTP {status}, not valid JSON")
    else:
        if headers.get("Access-Control-Allow-Origin") != "*":
            problems.append("/api/cves.json: no Access-Control-Allow-Origin: *")
        if sorted(p["slug"] for p in index["pages"]) != slugs:
            problems.append("/api/cves.json: pages don't match content/")
        if sorted(v["id"] for v in index["safe_versions"]) != products:
            problems.append("/api/cves.json: safe_versions don't match versions/")
    for kind, ids, key in (("", slugs, "slug"), ("versions/", products, "id")):
        for i in ids:
            status, _, body = get(f"{BASE}/{kind}{i}.json")
            try:
                ok = status == 200 and json.loads(body).get(key) == i
            except ValueError:
                ok = False
            if not ok:
                problems.append(f"/{kind}{i}.json: HTTP {status}, missing or wrong {key}")
    return problems


def main():
    problems, pages = [], 0
    status, _, sitemap = get(f"{BASE}/sitemap.xml")
    urls = re.findall(r"<loc>https://tldrcve\.com([^<]*)</loc>", sitemap.decode())
    if status != 200 or not urls:
        sys.exit(f"sitemap.xml: HTTP {status}, {len(urls)} URLs")
    for path in urls:
        pages += 1
        status, _, body = get(BASE + path)
        html = body.decode(errors="replace")
        if status != 200:
            problems.append(f"{path}: HTTP {status}")
            continue
        m = re.search(r'property="og:image" content="([^"]+)"', html)
        if not m:
            problems.append(f"{path}: no og:image")
            continue
        img = m.group(1).replace("https://tldrcve.com", BASE)
        expected = "default" if path == "/" else path.strip("/")
        if f"/assets/og/{expected}.png" not in img:
            problems.append(f"{path}: card is {img.rsplit('/', 1)[-1]}, expected its own ({expected}.png); run tools/cards.py")
        istatus, _, data = get(img)
        if istatus != 200 or png_size(data) != (1200, 630):
            problems.append(f"{path}: card {img} HTTP {istatus}, size {png_size(data)}")
        for tag in ('name="twitter:card" content="summary_large_image"', 'rel="icon"', 'rel="canonical"'):
            if tag not in html:
                problems.append(f"{path}: missing {tag}")
    for name in ("/favicon.ico", "/assets/icons/icon-32.png", "/assets/icons/apple-touch-icon.png", "/feed.xml", "/feed.json"):
        status, headers, _ = get(BASE + name)
        if status != 200:
            problems.append(f"{name}: HTTP {status}")
    for f in sorted((ROOT / "content").glob("*.json")):
        c = json.loads(f.read_text())
        for cid in c["cves"] + c.get("ghsa", []):
            status, headers, _ = get(f"{BASE}/{cid}", follow=False)
            loc = headers.get("Location", "") if headers else ""
            if status != 301 or not loc.rstrip("/").endswith(c["slug"]):
                problems.append(f"/{cid}: HTTP {status} -> {loc or 'nothing'}, expected /{c['slug']}/")
    problems += check_data(urls)
    for p in problems:
        print("FAIL", p)
    print(f"{pages} pages checked, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
