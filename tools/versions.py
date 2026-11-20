"""Refresh versions/<id>.json with the newest release on each line, from the vendor's own feed.

  python3 tools/versions.py          # update every product, print what changed
  python3 tools/versions.py --dry    # show what would change, write nothing
  python3 tools/versions.py --report # table: every product, how it's refreshed, when it was last checked, where we look

Never lowers a version: third-party feeds can lag, so a feed older than what we have is ignored.
After it runs, `python3 build.py --strict` checks every line is at or above the fixes on our pages.
"""
import json, re, sys, urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "versions"
UA = {"User-Agent": "tldrcve-versions"}


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read())


sys.path.insert(0, str(ROOT))
from build import vkey  # noqa: E402  (same version ordering as the build's checks)


def feed_php(_):
    """php.net's own list of the newest release per active branch."""
    out = {}
    for branches in get_json("https://www.php.net/releases/active.php").values():
        for line, rel in branches.items():
            ver = rel["source"][0]["filename"].removeprefix("php-").split(".tar")[0]
            out[line] = (ver, datetime.strptime(rel["date"], "%d %b %Y").date().isoformat())
    return out


def feed_endoflife(product):
    """endoflife.date: works for many products, but can lag the vendor by days."""
    return {c["cycle"]: (c["latest"], c.get("latestReleaseDate", "")) for c in get_json(f"https://endoflife.date/api/{product}.json")}


def feed_nodejs(_):
    """nodejs.org's own release index, newest first."""
    out = {}
    for r in get_json("https://nodejs.org/dist/index.json"):
        if "-" in r["version"]:  # alpha, beta, rc
            continue
        major = r["version"].lstrip("v").split(".")[0]
        out.setdefault(major, (r["version"].lstrip("v"), r["date"]))
    return out


def feed(name):
    kind, _, arg = name.partition(":")
    return {"php": feed_php, "nodejs": feed_nodejs, "endoflife": feed_endoflife}[kind](arg)


def report():
    """Markdown table of every product file: refresh method, last check, latest per line, and where we look."""
    today = date.today()
    rows = []
    for f in sorted(DIR.glob("*.json")):
        v = json.loads(f.read_text())
        age = (today - date.fromisoformat(v["checked"])).days
        how = f"feed `{v['feed']}`" if v.get("feed") else "by hand"
        lines = ", ".join(f"{l['line']} → {l['latest']}" for l in v["lines"]) or "—"
        if v.get("unfixed"):
            lines += "; no fix: " + ", ".join(u["line"] for u in v["unfixed"])
        where = " ".join(f"<{u}>" for u in v.get("latest_from", []))
        flag = " ⚠️" if age > 14 else ""
        rows.append(f"| [{v['name']}](versions/{f.name}) | {how} | {v['checked']} ({age}d){flag} | {lines} | {where} |")
    print("| Product | Refreshed | Last checked | Latest safe | Where we look |\n|---|---|---|---|---|")
    print("\n".join(rows))


def main():
    if "--report" in sys.argv:
        return report()
    dry = "--dry" in sys.argv
    for f in sorted(DIR.glob("*.json")):
        v = json.loads(f.read_text())
        if not v.get("feed"):
            print(f"{v['id']}: no feed yet; update by hand")
            continue
        try:
            latest = feed(v["feed"])
        except Exception as e:  # one broken feed shouldn't stop the others
            print(f"{v['id']}: feed failed ({e}); kept as is")
            continue
        changed = []
        for line in v["lines"]:
            ver, rel = latest.get(line["key"], (None, None))
            if ver and vkey(ver) > vkey(line["latest"]):
                changed.append(f"{line['line']}: {line['latest']} -> {ver}")
                line["latest"], line["released"] = ver, rel or line.get("released", "")
            elif ver and vkey(ver) < vkey(line["latest"]):
                print(f"{v['id']} {line['line']}: feed says {ver}, we have {line['latest']}; feed lags, ignored")
        known = {l["key"] for l in v["lines"]}
        for new in sorted(set(latest) - known, key=vkey, reverse=True):
            if all(vkey(new) > vkey(k) for k in known):
                print(f"{v['id']}: new line {new} ({latest[new][0]}) in the feed; add it by hand after checking it")
        v["checked"] = date.today().isoformat()
        print(f"{v['id']}: " + ("; ".join(changed) if changed else "no new releases"))
        if not dry:
            f.write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
