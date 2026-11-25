# AGENTS.md

Instructions for AI agents (and people) working in this repository.

tldrcve.com explains the vulnerabilities people are talking about in plain English: how scary it is, whether you're affected, and what to do. Every claim is sourced. Accuracy matters more than speed or coverage.

## Layout

| Path | What it is |
|---|---|
| `content/<slug>.json` | One file per vulnerability. Most changes touch only this folder |
| `build.py` | Builds the static site into `site/`, plus files for agents: `/llms.txt`, `/<slug>.json`, `/versions/<product>.json` and the `/api/cves.json` index. Python standard library only |
| `assets/` | `site.css`, `site.js`, and `og/` (link-preview images) |
| `versions/<product>.json` | Latest safe version per product line, shared by every page that embeds it. Edit once, every page updates |
| `/incidents/` | The Incidents list, built from pages with `"kind": "incident"`. They are left out of All CVEs, but its search finds them |
| `calendar.json` | Scheduled release and patch days (Patch Tuesday, Chrome, Firefox, Oracle, PHP…), each with a source that states the date or the rule, and a `note`: one line on whose schedule it is and what it means for readers ("Google's scheduled stable release day. Chrome updates itself; relaunch it to finish."). Mark unannounced dates `"expected": true` |
| `weeks/<yyyy>-w<nn>.json` | One file per weekly review (`week`, optional `intro`). The rest of `/week/…` is built from the data: new pages, changes, safe releases and the next 30 days (calendar, pending fixes, CISA deadlines). On the Monday after a week ends, freeze it with `python3 build.py --freeze-week YYYY-Www` so its page stops changing; the build prints a reminder |
| `watch/<id>.json` | Vulnerabilities we evaluated but haven't written a page for, with the facts, sources, what would change our mind, and a recheck date |
| `tools/versions.py` | Refreshes `versions/` from release feeds (vendor indexes, npm, PyPI, GitHub releases, endoflife.date). Never lowers a version or adds a line by itself. `--check` writes nothing and lists what to look at (the daily digest runs it); `--report` lists every product, how it's refreshed, when it was last checked and where we look |
| `tools/check_live.py` | Checks the live site after a deploy: every page, its own preview image, icons, feed, redirects, `llms.txt` and the JSON files |
| `tools/cards.py` | Renders the link-preview images. Needs a desktop browser (Chrome, Firefox or Zen) |
| `site/` | Build output. Never edit or commit it |

## Build and check locally

```bash
python3 build.py --strict                                   # build; fails on any warning
python3 -m http.server 4321 --directory site                # preview at http://localhost:4321
```

## How changes go live

1. Open a pull request. The `build` check renders any missing preview images (no browser needed on your side) and runs `build.py --strict --public`. It must pass before merging; the rendered images are attached to the run for review.
2. A maintainer reviews and merges. Nobody can force-push to or delete `main`.
3. Every push to `main` deploys automatically (`.github/workflows/deploy.yml`): build, deploy to Cloudflare, wait until the new build is live, then `tools/check_live.py` checks every page.

Pull requests never see the Cloudflare token: it lives in the `production` environment, which only `main` can use. Workflows from first-time and outside contributors wait for a maintainer to approve them, and only GitHub's own actions, pinned to a commit, are allowed.

Manual deploy (maintainers, emergencies only):

```bash
python3 build.py --strict --public
CLOUDFLARE_API_TOKEN=… npx wrangler@4.165.0 deploy
python3 tools/check_live.py
```

Without `--public` the build tells search engines not to index the site.

The build warns about:
- names longer than 18 characters
- card labels longer than 26 characters
- relative dates ("today")
- overdue pending items
- a missing `needs` field when `no_login` is false
- a page not tied to any Safe versions product and without `versions_skip`
- a calendar event without an https source or a `note`, or an `expected` date that has passed

A change is only done when `--strict` passes.

Every page needs its own link-preview image: `--strict` fails until a new page (or product in `versions/`) has one. Run `python3 tools/cards.py` if you have Chrome, Firefox or Zen; if not, open the pull request anyway and CI draws them. If you change a page's name, CVEs, verdict, scare level or tile line, its image goes out of date: the build prints a note, and `--public` builds refuse to deploy until it's redrawn.

`tools/check_live.py` runs after every deploy. It loads every page in the sitemap and fails if a page, its preview image, the favicon, the feed, a CVE/GHSA redirect, `llms.txt` or a JSON file is wrong.

## Writing a page

Copy the shape of an existing file (`content/nginx2root.json` is a good model).

| Field | What it is |
|---|---|
| `slug` | URL path, kebab-case |
| `kind` | Optional: `vulnerability` (default) or `incident`. An incident already happened to someone (a vendor-side compromise, a breach). Its page shows an "Incident" badge instead of a patch verdict, "How bad is it?" with the incident meter, "Were you hit?" only when there's something readers can check, and "Clean up" instead of "What to do". Incidents are listed under Incidents, not All CVEs. See How we rate |
| `incident` | Incidents only: `checks`, each of `confirmed`, `taken`, `reach`, `entry`, `contained` as `{"state": "yes" \| "part" \| "no", "cite": [...]}`. They set the "How bad is it?" checklist and must agree with `status.scare` (Minor, Notable, Serious, Severe). `entry` also gives the badge's "Entry point known / named / unknown" |
| `orgs` | Optional: the organisations a page is about, spelled out and linked: `[{"name": "Office of the Director of National Intelligence (ODNI)", "url": "https://www.dni.gov/"}]`. Shown at the top of the page; use it on every incident |
| `related` | Optional: slugs of our own pages to link under "Clean up" (or "What to do"), for example the CVE page an incident is tied to |
| `root_cause` | Incidents only: `tags` (one or more of `vendor-flaw`, `supply-chain`, `known-bug`, `zero-day`, `stolen-login`, `misconfig`, `unknown`), optional `text` and `cite`. |
| `timeline` | Optional, mainly for incidents: "What's confirmed", `date`, `text`, `cite` and `who`: `record` (on the record), `official` (unnamed official), `anonymous` (anonymous source) or `press` (press report only). Label every line by who says it |
| `name` | Display name or nickname, **≤ 18 chars** (one line on every card) |
| `aliases` | Lowercase search terms: products, nicknames, related CVE IDs |
| `cves` | CVE IDs; `[]` if none assigned yet |
| `ghsa` | Optional: GitHub advisory IDs. Each CVE and GHSA ID also works as a URL (`tldrcve.com/CVE-…`) |
| `product` | Main product. The card label must stay ≤ 26 chars |
| `also_in` | Optional: other products that bundle it, shown as "Product (First +N more)" |
| `disclosed` | `YYYY-MM-DD`, when the bug was made public (drives the All CVEs date filter) |
| `news` | Optional: when it became news, if later than `disclosed` (the date on All CVEs tiles; "Latest" on the homepage is ordered by the newest `changes[]` entry that isn't `minor`) |
| `updated` | `YYYY-MM-DD` of the last edit |
| `verdict` | `now`, `if`, `cycle` or `watch` (see below) |
| `tile_line` | The reason for the verdict, about 55 chars max. It sits next to the verdict badge and on the link card, so never repeat the verdict or the action ("Exploited, no login. In CISA KEV.", not "Patch now.") |
| `tldr` | **Required, ≤ 256 chars.** The answer, in up to three short, plain sentences, in this order: what it is, how scary (exploit, attacks, KEV), who is affected, what to do. Don't open with the page's nickname ("NoisyTCP: …"; the title is right above); the product as the subject ("SGLang, a popular AI model server, …") is fine. No commands, lists of several fixed versions, or dates that go stale (KEV due dates); one affected range or one version to update to is fine. Used at the top of the page and as the meta description, the feed item and the "Copy TL;DR" text. Every claim must already be on the page; update it whenever the verdict, status or fix changes. When it corrects something the page said before, add a `changes[]` entry so feed readers see the correction |
| `summary` | **More details**, under the TL;DR: 1-3 sentences with only what the TL;DR leaves out, such as how the bug works, who found it, numbers, where sources disagree, related bugs, useful trivia and the one setting or command that matters most. Never repeat the TL;DR, but don't drop facts either: each one belongs in the TL;DR, here, or a section below |
| `status.exploit` | `public` (working code anyone can download), `demonstrated` (shown, code not public) or `none` |
| `status.attacks` | `seen` (a credible, named report) or `none` |
| `status.kev` | `{"added": "...", "due": "..."}` from CISA's KEV catalog, or `null` |
| `status.cisa_alert` | Optional `true`: CISA alert, but not on KEV |
| `status.no_login` | Optional `true`/`false`; leave out when it depends |
| `status.needs` | Required when `no_login` is `false`: exactly what access the attacker needs |
| `status.scare` | 0-4: 0-1 Shrug, 1-2 Keep an eye on it, 2-3 Check today, 3-4 Drop everything |
| `affected[]` | Conditions that must **all** be true: `label`, `text`, optional `cmd`, `cite`. Optional on incidents: leave it out when readers have nothing to check |
| `do[]` | Steps: `label`, `text`, optional `cmd`, `cite`, optional `pending: {"expected": "YYYY-MM-DD"}`, optional `versions: ["php"]` to show that product's latest safe versions in the step |
| `fixed_in` | Optional: first fixed version per product line, e.g. `{"php": {"8.5": "8.5.13"}}`. Keys match `versions/<product>.json`. Leave it out when there is no fix |
| `versions_skip` | Optional: why the page has no Safe versions product, e.g. fixes exist only as distro packages. Every other page must be tied to one: `fixed_in` when a fix is released, or an `unfixed` entry in `versions/<product>.json` while it's pending |
| `bugs` | Optional, makes the page a release roundup: one entry per advisory with `cve`, `project`, `severity`, `url`; critical and high ones also get `title`, `text`, `verdict` and optional `page` (slug of the bug's own page, which then links back). Leave a bug's CVE out of `cves` when it has its own page |
| `sources[]` | `title` ("Publisher: what it supports"), `url`, optional `date`. `cite` numbers are 1-based indexes into this list |
| `changes[]` | `date` and `text`, newest first; the last entry is "Published." One entry per page per day: add to today's entry rather than starting a second one. Every entry becomes an RSS/JSON Feed item ("What changed" plus the current TL;DR; CVE pages in `/feed.xml`, incidents in `/incidents/feed.xml`, both in `/all/feed.xml`) and moves the page up in "Latest", **unless** it has `"minor": true`. Leave `minor` off when the verdict or scare level changes, exploit, attack or KEV status changes, a fix is released or the advice changes, who is affected changes, or it corrects something a reader could have acted on. Set it for wording, sources, aliases and rechecks that changed nothing |

### Card, TL;DR and More details

Each layer has one job, from a glance to the proof:

| | Link card | TL;DR | More details |
|---|---|---|---|
| Job | The verdict at a glance wherever a link is shared | The answer for someone on the page | What the answer leaves out |
| Text we write | `name`, `tile_line` (the card also shows the CVEs, verdict and scare level) | `tldr` | `summary` |
| Time | Redrawn when it changes, but platforms cache it when shared | Always current | Current; dated facts carry their dates |

Below them, the checklist, "Are you affected?", "What to do" and the sources hold the detail and the proof. Social posts are written per post, outside this repo; they start from the TL;DR but add a headline line with the name, CVE and decision.

### Product version files (`versions/<product>.json`)

`id`, `name`, `about`, `feed` (a `tools/versions.py` feed, or `null` for by hand), `latest_from` (URLs where the newest releases are checked), `filter` (All CVEs search term), `checked` (date of the last check), `lines[]` (`line`, `key`, `latest`, optional `released`, `note`), optional `older`, `unfixed[]` (`line`, `note`, `pages`), optional `skip_lines` (`{"4.2": "why we don't list it"}`: a newer line left out on purpose, so `--check` stops flagging it) and `sources[]`. Update `checked` every time you look, even if nothing changed. The build notes products not checked for 14 days. A feed is a hint, not a source: confirm every change on the vendor's page in `latest_from` before it ships, then run `python3 tools/cards.py` (a changed version redraws the product's card) and open a pull request. Products without a feed are checked by hand; `--check` lists them after 7 days.

### Evaluated, no page (`watch/<id>.json`)

When a vulnerability gets attention but doesn't qualify yet, record it instead of dropping it: `id`, `title`, `cves`, `product`, `evaluated`, `decision` (`watch`, `page` or `dropped`), `why`, `page_if` (what would change our mind), `recheck` (date), `facts[]` (`text`, `cite`), `sources[]`, `history[]` (`date`, `text`, newest first). On each recheck, add a `history` entry and a new `recheck` date. When it gets a page, set `decision` to `page` and add `"page": "<slug>"`; the build fails if a watched CVE already has a page.

### Rules
- **Sources:**
  - Every claim has a source that actually says it.
  - Prefer primary sources: vendor advisories, the CISA KEV catalog, the CVE/NVD record, the researcher's write-up, distro trackers.
  - A CVE or GHSA ID named in the vendor's advisory or release notes counts, even before the CVE record is published or the GHSA reaches GitHub's reviewed database.
  - Our own advice is allowed when the text says it's ours ("Grafana doesn't say to rotate anything; we would, because…"). The facts it rests on still need sources.
- **No invention:**
  - Never invent versions, flags, commands or dates.
  - When sources conflict, say so on the page.
- **"Are you affected?"** lists only conditions that must all be true. No "or" items. Fold "not affected if…" details into the matching condition.
- **Commands** must be exact. Commands that check something ("Are you affected?" and any step that only looks) must be read-only. A fix step may quote the vendor's own upgrade, install or restart command exactly as the vendor gives it (`mix local.hex --force`).
- Text fields support `code` and links to site pages only: `[label](/slug/)`.
- **Verdict, checklist and scare level** must agree:
  - `now`: working exploit or attacks seen (a CISA KEV listing counts), and either common setups are exposed or readers can't rule themselves out: the vendor doesn't say which setups are exposed and the vulnerable part is reachable by default. When it's the second, the page says so in a "Why it's Patch now" step.
  - `if`: serious, but only under conditions the page lists.
  - `cycle`: real, but hard to reach or low impact.
  - `watch`: getting attention, but too little is known to act on (no details, no fix, no exploit). Never a softer `now`. The page must say what would change the verdict.
- **Writing:**
  - Plain English and short. No hype words unless quoting an official rating.
  - Loaded terms (RCE, zero-day, wormable) follow common usage, not just the source's wording. RCE means an attacker reaches the target over the network without the user doing something like opening a file; if the user has to open or display something, call it code or command execution. Keep the source's term as an alias so people can still find the page. When a vendor's official title says RCE, quote it as the vendor's wording.
  - Absolute dates only ("19 Nov 2026").
  - `pending` is for something a source says is coming (a fix, release or advisory), with the date that source gives. If the source gives no date, there's no `pending`: say it in the text ("in the coming days, no date given"). Our own recheck dates ("We'll check again by 1 Dec 2026") are plain text, never `pending`.

Maintainers run an additional review before anything is merged.

**Independent verification before merge.** Every pull request that changes data (pages, `versions/`, `watch/`) gets checked by a separate agent (Claude Opus 5.5) before it merges. That agent didn't write the change. It opens every source and confirms each data point in the diff: versions, dates, CVE IDs, verdict inputs (exploit, attacks, KEV), commands and quotes. It reports anything a source doesn't say. Fix or remove every finding, then verify again; merge only when nothing is left.
