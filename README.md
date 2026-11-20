# tldrcve

**[tldrcve.com](https://tldrcve.com)**: the vulnerabilities everyone's talking about, in plain English.
<br />How scary is it, are you affected, and what should you do?

Each page gives you:
- a verdict ("Patch now", "Patch now if…", "Next cycle") and a scare-o-meter
- the conditions that must all be true for you to be affected, with commands to check each one
- what to do: the fix, the latest safe versions, a stopgap, and clean-up
- a source for every claim, and a changelog

[Safe versions](https://tldrcve.com/versions/) lists the newest release on each product line that fixes every bug we cover, and flags lines with no fix.

Follow [@tldrcve](https://x.com/tldrcve) on X or the [RSS feed](https://tldrcve.com/feed.xml) for new pages and updates.

## How it works

A static site with no server code and no dependencies beyond Python's standard library.

| Path | What it is |
|---|---|
| `content/<slug>.json` | One file per vulnerability |
| `versions/<product>.json` | Latest safe version per product line, shared by every page that uses it |
| `build.py` | Builds everything into `site/` |
| `tools/versions.py` | Refreshes `versions/` from vendor feeds |
| `tools/cards.py` | Renders the link-preview images in `assets/og/` (needs a desktop browser) |

## Build it locally

```bash
python3 build.py --strict
python3 -m http.server 4321 --directory site
```

Then open http://localhost:4321.

## Found a mistake, or a bug we should cover?

Open an issue with a link to the source that shows it, or send a pull request that edits the file in `content/` or `versions/`. Run `python3 build.py --strict` first if you can; the pull request check runs it too. Merged changes go live automatically. [AGENTS.md](AGENTS.md) explains every field and the writing rules; they apply to people and AI agents alike.

We only cover vulnerabilities people are actually talking about, and accuracy beats speed: every claim needs a source that says it.

## License

- Code (`build.py`, `tools/`, `assets/site.*`): [MIT](LICENSE)
- Content (`content/`, `versions/`, `assets/og/`): [CC BY 4.0](LICENSE-CONTENT). Reuse it with attribution to tldrcve.com.
