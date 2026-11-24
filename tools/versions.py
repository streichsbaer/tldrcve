"""Refresh versions/<id>.json with the newest release on each line, from the vendor's own feed.

  python3 tools/versions.py          # update every product, print what changed
  python3 tools/versions.py --dry    # show what would change, write nothing
  python3 tools/versions.py --report # table: every product, how it's refreshed, when it was last checked, where we look
  python3 tools/versions.py --check  # writes nothing; one labelled line per thing to look at (for the daily digest)

Never lowers a version: third-party feeds can lag, so a feed older than what we have is ignored.
A feed is a hint, not a source: confirm every change on the vendor's own page (latest_from) before it ships,
and ship it through a pull request. After it runs, `python3 build.py --strict` checks every line is at or
above the fixes on our pages.

Feeds (the `feed` field in versions/<id>.json):
  php, nodejs, dotnet, wordpress   the vendor's own release index
  endoflife:<product>              endoflife.date, keyed by its cycle names
  npm:<package>[:major]            newest release per major.minor (or per major) from the npm registry
  pypi:<package>[:major]           the same from PyPI
  github:<owner/repo>[:major]      the same from GitHub releases (drafts and pre-releases skipped)
  npm-latest:<a>,<b> / pypi-latest:<a>,<b>   newest release of each package, keyed by package name
  distro-kernel                    the distributions' own kernel packages, keyed like the linux-kernel lines:
                                   "Debian 13" (Debian's archive, main + security + updates), "Ubuntu 24.04"
                                   (Launchpad, LTS releases of the last five years; Release, Security and Updates
                                   pockets, not Proposed),
                                   "RHEL 10.3" per minor stream and "RHEL 9" for the newest of a major (Red Hat's
                                   security data API, the `kernel` package)
"""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "versions"
UA = {"User-Agent": "tldrcve-versions"}


def get_json(url, timeout=30):
    headers = dict(UA)
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"  # only raises the rate limit
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read())


def get_text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA)), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


PRE = re.compile(r"(rc|alpha|beta|preview|candidate|snapshot|dev|canary|nightly|next|\bM\d)", re.I)
VERSION = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?(?![\d.])")


def newest_per_line(releases, by="minor"):
    """releases: [(version, date)]. Returns {line: (version, date)}, line = "16.4" (minor) or "16" (major)."""
    out = {}
    for ver, rel in releases:
        parts = ver.split(".")
        line = parts[0] if by == "major" else ".".join(parts[:2])
        if line not in out or vkey(ver) > vkey(out[line][0]):
            out[line] = (ver, rel)
    return out


def split_arg(arg):
    name, _, by = arg.partition(":")
    return name, (by or "minor")


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


def feed_dotnet(_):
    """Microsoft's own .NET release index, keyed by major ("10")."""
    idx = get_json("https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json")
    return {r["channel-version"].split(".")[0]: (r["latest-release"], r["latest-release-date"]) for r in idx["releases-index"]}


def feed_wordpress(_):
    """WordPress.org's own list of every release; the newest per branch ("7.1"). No dates."""
    vers = [v for v in get_json("https://api.wordpress.org/core/stable-check/1.0/") if re.fullmatch(r"\d+\.\d+(\.\d+)?", v)]
    return newest_per_line([(v, "") for v in vers])


def feed_npm(arg):
    name, by = split_arg(arg)
    d = get_json(f"https://registry.npmjs.org/{name}")
    vers = [v for v in d["versions"] if re.fullmatch(r"\d+\.\d+\.\d+", v) and not d["versions"][v].get("deprecated")]
    return newest_per_line([(v, d["time"].get(v, "")[:10]) for v in vers], by)


def feed_pypi(arg):
    name, by = split_arg(arg)
    d = get_json(f"https://pypi.org/pypi/{name}/json")
    rels = [(v, files[0]["upload_time"][:10]) for v, files in d["releases"].items()
            if files and re.fullmatch(r"\d+(\.\d+)+", v) and not all(f.get("yanked") for f in files)]
    return newest_per_line(rels, by)


def feed_github(arg):
    repo, by = split_arg(arg)
    rels = []
    for r in get_json(f"https://api.github.com/repos/{repo}/releases?per_page=100"):
        label = f'{r.get("tag_name") or ""} {r.get("name") or ""}'
        if r.get("draft") or r.get("prerelease") or PRE.search(label):
            continue
        m = VERSION.search(r.get("tag_name") or "") or VERSION.search(r.get("name") or "")
        if m:
            rels.append((".".join(g for g in m.groups() if g is not None), (r.get("published_at") or "")[:10]))
    return newest_per_line(rels, by)


def feed_latest(kind, arg):
    """Newest release of each named package, keyed by package name (for products whose lines are packages)."""
    out = {}
    for name in arg.split(","):
        lines = (feed_npm if kind == "npm" else feed_pypi)(name)
        ver, rel = max(lines.values(), key=lambda x: vkey(x[0]))
        out[name] = (ver, rel)
    return out


def feed_nodejs(_):
    """nodejs.org's own release index, newest first."""
    out = {}
    for r in get_json("https://nodejs.org/dist/index.json"):
        if "-" in r["version"]:  # alpha, beta, rc
            continue
        major = r["version"].lstrip("v").split(".")[0]
        out.setdefault(major, (r["version"].lstrip("v"), r["date"]))
    return out


DEBIAN = {"11": "bullseye", "12": "bookworm", "13": "trixie", "14": "forky"}
RHEL_KERNEL = re.compile(r"^kernel-0:(\d+\.\d+\.\d+-[\d.]+\.el(\d+)(?:_(\d+))?)\.src$")


def debkey(v):
    """Debian ordering for one detail build.vkey misses: "~" sorts lower ("6.12.118-1~deb12u1" < "6.12.118-1")."""
    base, tilde, rest = v.partition("~")
    return (vkey(base), 0 if tilde else 1, vkey(rest) if tilde else ())


def kernel_debian():
    """Debian's archive (madison): the newest linux source per release, from its main, security and updates suites."""
    out = {}
    for number, name in DEBIAN.items():
        suites = f"{name},{name}-security,{name}-updates"
        text = get_text(f"https://qa.debian.org/madison.php?package=linux&table=debian&text=on&s={suites}")
        vers = [row.split("|")[1].strip() for row in text.splitlines() if row.count("|") >= 3 and row.split("|")[0].strip() == "linux"]
        if vers:
            out[f"Debian {number}"] = (max(vers, key=debkey), "")
    return out


def kernel_ubuntu():
    """Launchpad: the newest published linux source per LTS release of the last five years (standard support), from its
    Release, Security and Updates pockets. Launchpad answers slowly (about 10 s a release), hence the longer timeout."""
    out = {}
    for series in get_json("https://api.launchpad.net/1.0/ubuntu/series", timeout=90)["entries"]:
        version = series["version"]
        year, month = (int(x) for x in version.split("."))
        if series["status"] == "Obsolete" or month != 4 or year % 2 or year < date.today().year % 100 - 5:
            continue
        query = urllib.parse.urlencode({"ws.op": "getPublishedSources", "source_name": "linux", "exact_match": "true",
                                        "status": "Published", "distro_series": series["self_link"]})
        pubs = [e for e in get_json(f"https://api.launchpad.net/1.0/ubuntu/+archive/primary?{query}", timeout=90)["entries"]
                if e["pocket"] in ("Release", "Security", "Updates")]
        if pubs:
            newest = max(pubs, key=lambda e: vkey(e["source_package_version"]))
            out[f"Ubuntu {version}"] = (newest["source_package_version"], (newest.get("date_published") or "")[:10])
    return out


def kernel_redhat():
    """Red Hat's security data: the newest `kernel` build per RHEL minor stream (el9_9 -> "RHEL 9.9") and per major
    ("RHEL 9", the newest of any of its streams), from the last year's advisories."""
    after = date.fromordinal(date.today().toordinal() - 365).isoformat()
    advisories, page = [], 1
    while True:
        batch = get_json(f"https://access.redhat.com/hydra/rest/securitydata/csaf.json?package=kernel&after={after}&per_page=1000&page={page}")
        advisories += batch
        if len(batch) < 1000:
            break
        page += 1
    out = {}
    for a in advisories:
        for pkg in a.get("released_packages", []):
            m = RHEL_KERNEL.match(pkg)
            if not m:
                continue
            ver, major, minor = m.groups()
            for key in ([f"RHEL {major}.{minor}"] if minor else []) + [f"RHEL {major}"]:
                if key not in out or vkey(ver) > vkey(out[key][0]):
                    out[key] = (ver, a.get("released_on", "")[:10])
    return out


def feed_distro_kernel(_):
    """Each distribution on its own: one that fails (Launchpad is slow) is reported and the others still count."""
    out, failed = {}, []
    for name, fetch in (("debian", kernel_debian), ("ubuntu", kernel_ubuntu), ("redhat", kernel_redhat)):
        try:
            out.update(fetch())
        except Exception as e:
            failed.append(name)
            print(f"FEED FAILED versions/linux-kernel (distro-kernel, {name}): {e}")
    if len(failed) == 3:
        raise RuntimeError("every distribution failed")
    return out


def feed(name):
    kind, _, arg = name.partition(":")
    return {"php": feed_php, "nodejs": feed_nodejs, "endoflife": feed_endoflife, "dotnet": feed_dotnet,
            "wordpress": feed_wordpress, "npm": feed_npm, "pypi": feed_pypi, "github": feed_github,
            "npm-latest": lambda a: feed_latest("npm", a), "pypi-latest": lambda a: feed_latest("pypi", a),
            "distro-kernel": feed_distro_kernel}[kind](arg)


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


HAND_DAYS = 7  # --check lists by-hand products not looked at for this many days


def refresh(v, latest):
    """Apply a feed to one product (in place). Returns (changes, notes); never lowers a version."""
    changes, notes = [], []
    for line in v["lines"]:
        ver, rel = latest.get(line["key"], (None, None))
        if ver and vkey(ver) > vkey(line["latest"]):
            changes.append(f"{line['line']}: {line['latest']} -> {ver}" + (f" ({rel})" if rel else ""))
            line["latest"] = ver
            if rel:
                line["released"] = rel
        elif ver and vkey(ver) < vkey(line["latest"]):
            notes.append(f"{line['line']}: feed says {ver}, we have {line['latest']}; feed lags, ignored")
    known = {l["key"] for l in v["lines"]}
    skipped = set(v.get("skip_lines", {}))  # newer lines we chose not to list; the reason is in the file
    for new in sorted(set(latest) - known - skipped, key=vkey, reverse=True):
        if known and all(vkey(new) > vkey(k) for k in known):
            notes.append(f"new line {new} ({latest[new][0]}) in the feed; add it by hand after checking it")
    if not v["lines"]:  # nothing fixed yet: say when a new release appears, it may be the fix
        newest = max(latest.values(), key=lambda x: vkey(x[0]))
        if newest[1] and (date.today() - date.fromisoformat(newest[1])).days <= HAND_DAYS:
            notes.append(f"new release {newest[0]} ({newest[1]}); check whether it fixes: "
                         + "; ".join(u["line"] for u in v.get("unfixed", [])))
    return changes, notes


def check():
    """For the daily digest: what changed upstream, and which by-hand products are due. Writes nothing."""
    out = []
    today = date.today()
    for f in sorted(DIR.glob("*.json")):
        v = json.loads(f.read_text())
        if not v.get("feed"):
            age = (today - date.fromisoformat(v["checked"])).days
            if age >= HAND_DAYS:
                out.append(f"CHECK BY HAND versions/{v['id']} (last checked {age}d ago): {' '.join(v.get('latest_from', []))}")
            continue
        try:
            latest = feed(v["feed"])
        except Exception as e:
            out.append(f"FEED FAILED versions/{v['id']} ({v['feed']}): {e}")
            continue
        changes, notes = refresh(v, latest)
        out += [f"UPDATE? versions/{v['id']} {c}" for c in changes]
        out += [f"LOOK versions/{v['id']}: {n}" for n in notes if "feed lags" not in n]
    print("\n".join(out) if out else "Safe versions: nothing to do.")


def main():
    if "--report" in sys.argv:
        return report()
    if "--check" in sys.argv:
        return check()
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
        changes, notes = refresh(v, latest)
        for n in notes:
            print(f"{v['id']}: {n}")
        v["checked"] = date.today().isoformat()
        print(f"{v['id']}: " + ("; ".join(changes) if changes else "no new releases"))
        if not dry:
            f.write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
