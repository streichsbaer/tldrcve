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
| `watch/<id>.json` | Vulnerabilities we evaluated but haven't written a page for, with the facts, sources, what would change our mind, and a recheck date |
| `tools/versions.py` | Refreshes `versions/` from vendor feeds (PHP, Node.js so far). Never lowers a version. `--report` lists every product, how it's refreshed, when it was last checked and where we look |
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

A change is only done when `--strict` passes.

Every page needs its own link-preview image: `--strict` fails until a new page (or product in `versions/`) has one. Run `python3 tools/cards.py` if you have Chrome, Firefox or Zen; if not, open the pull request anyway and CI draws them. If you change a page's name, CVEs, verdict, scare level or tile line, its image goes out of date: the build prints a note, and `--public` builds refuse to deploy until it's redrawn.

`tools/check_live.py` runs after every deploy. It loads every page in the sitemap and fails if a page, its preview image, the favicon, the feed, a CVE/GHSA redirect, `llms.txt` or a JSON file is wrong.

## Writing a page

Copy the shape of an existing file (`content/nginx2root.json` is a good model).

| Field | What it is |
|---|---|
| `slug` | URL path, kebab-case |
| `name` | Display name or nickname, **≤ 18 chars** (one line on every card) |
| `aliases` | Lowercase search terms: products, nicknames, related CVE IDs |
| `cves` | CVE IDs; `[]` if none assigned yet |
| `ghsa` | Optional: GitHub advisory IDs. Each CVE and GHSA ID also works as a URL (`tldrcve.com/CVE-…`) |
| `product` | Main product. The card label must stay ≤ 26 chars |
| `also_in` | Optional: other products that bundle it, shown as "Product (First +N more)" |
| `disclosed` | `YYYY-MM-DD`, when the bug was made public (drives the All CVEs date filter) |
| `news` | Optional: when it became news, if later than `disclosed` (drives "Latest" on the homepage) |
| `updated` | `YYYY-MM-DD` of the last edit |
| `verdict` | `now`, `if`, `cycle` or `watch` (see below) |
| `tile_line` | One line explaining the verdict, about 55 chars max |
| `summary` | 2-3 plain-English sentences |
| `status.exploit` | `public` (working code anyone can download), `demonstrated` (shown, code not public) or `none` |
| `status.attacks` | `seen` (a credible, named report) or `none` |
| `status.kev` | `{"added": "...", "due": "..."}` from CISA's KEV catalog, or `null` |
| `status.cisa_alert` | Optional `true`: CISA alert, but not on KEV |
| `status.no_login` | Optional `true`/`false`; leave out when it depends |
| `status.needs` | Required when `no_login` is `false`: exactly what access the attacker needs |
| `status.scare` | 0-4: 0-1 Shrug, 1-2 Keep an eye on it, 2-3 Check today, 3-4 Drop everything |
| `affected[]` | Conditions that must **all** be true: `label`, `text`, optional `cmd`, `cite` |
| `do[]` | Steps: `label`, `text`, optional `cmd`, `cite`, optional `pending: {"expected": "YYYY-MM-DD"}`, optional `versions: ["php"]` to show that product's latest safe versions in the step |
| `fixed_in` | Optional: first fixed version per product line, e.g. `{"php": {"8.5": "8.5.13"}}`. Keys match `versions/<product>.json`. Leave it out when there is no fix |
| `bugs` | Optional, makes the page a release roundup: one entry per advisory with `cve`, `project`, `severity`, `url`; critical and high ones also get `title`, `text`, `verdict` and optional `page` (slug of the bug's own page, which then links back). Leave a bug's CVE out of `cves` when it has its own page |
| `slack` | Paste-ready summary paragraph, no URL |
| `sources[]` | `title` ("Publisher: what it supports"), `url`, optional `date`. `cite` numbers are 1-based indexes into this list |
| `changes[]` | `date` and `text`, newest first; the last entry is "Published." |

### Product version files (`versions/<product>.json`)

`id`, `name`, `about`, `feed` (a `tools/versions.py` feed, or `null` for by hand), `latest_from` (URLs where the newest releases are checked), `filter` (All CVEs search term), `checked` (date of the last check), `lines[]` (`line`, `key`, `latest`, optional `released`, `note`), optional `older`, `unfixed[]` (`line`, `note`, `pages`) and `sources[]`. Update `checked` every time you look, even if nothing changed. The build notes products not checked for 14 days.

### Evaluated, no page (`watch/<id>.json`)

When a vulnerability gets attention but doesn't qualify yet, record it instead of dropping it: `id`, `title`, `cves`, `product`, `evaluated`, `decision` (`watch`, `page` or `dropped`), `why`, `page_if` (what would change our mind), `recheck` (date), `facts[]` (`text`, `cite`), `sources[]`, `history[]` (`date`, `text`, newest first). On each recheck, add a `history` entry and a new `recheck` date. When it gets a page, set `decision` to `page` and add `"page": "<slug>"`; the build fails if a watched CVE already has a page.

### Rules
- **Sources:**
  - Every claim has a source that actually says it.
  - Prefer primary sources: vendor advisories, the CISA KEV catalog, the CVE/NVD record, the researcher's write-up, distro trackers.
- **No invention:**
  - Never invent versions, flags, commands or dates.
  - When sources conflict, say so on the page.
- **"Are you affected?"** lists only conditions that must all be true. No "or" items. Fold "not affected if…" details into the matching condition.
- **Commands** must be read-only and exact.
- Text fields support `code` and links to site pages only: `[label](/slug/)`.
- **Verdict, checklist and scare level** must agree:
  - `now`: working exploit or attacks seen, and common setups are exposed.
  - `if`: serious, but only under conditions the page lists.
  - `cycle`: real, but hard to reach or low impact.
  - `watch`: getting attention, but too little is known to act on (no details, no fix, no exploit). Never a softer `now`. The page must say what would change the verdict.
- **Writing:**
  - Plain English and short. No hype words unless quoting an official rating.
  - Absolute dates only ("19 Nov 2026").
  - Mark anything still expected as `pending` with an expected date.

Maintainers run an additional review before anything is merged.
