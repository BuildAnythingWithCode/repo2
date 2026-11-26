#!/usr/bin/env python3
"""Build the public website: the dashboard, the write-up and today's data files.

Run it after the daily refresh:

    python3 -I scripts/refresh.py
    python3 -I scripts/build_site.py

It writes a static site to _site/ (git-ignored):

    index.html          the dashboard: dashboard/index.html inside a plain web page
    how-it-works.html   the write-up: WRITEUP.md as a web page
    data/*.json         the ten data files from out/dashboard/
    app.js, style.css   the dashboard's own code and styles
    shim.js, theme.css  what Claude's dashboard runtime provides there: the data loader and the colours
    vendor/d3.min.js    the charting library

The dashboard page is the same file Claude's dashboard uses. The lines of it that only make sense
inside Claude are swapped here (see PAGE_SWAPS). Needs the `markdown` package
(requirements-site.txt). To look at the result:  python3 -m http.server -d _site
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site"
DASH = ROOT / "dashboard"
DATA = ROOT / "out" / "dashboard"
OUT = ROOT / "_site"

REPO_URL = "https://github.com/BuildAnythingWithCode/repo2"
SITE_URL = "https://buildanythingwithcode.github.io/repo2/"
FILES = ["history", "today", "indicators", "turns", "zones", "blind", "early", "grades", "baselines", "strategy"]

# Lines of the dashboard page that only make sense inside Claude, and what the website shows instead.
PAGE_SWAPS = [
    ('href="https://github.com/BuildAnythingWithCode/repo2/blob/main/WRITEUP.md"', 'href="how-it-works.html"'),
    ("Open Sources on this page to see the rows and the code behind any number.",
     'Every number on this page comes from ten data files published with it, such as '
     '<a href="data/today.json">today.json</a> and <a href="data/history.json">history.json</a>.'),
]


def fail(msg: str) -> None:
    print(f"FAILED: {msg}")
    sys.exit(1)


def load_today() -> dict:
    missing = [n for n in FILES if not (DATA / f"{n}.json").is_file()]
    if missing:
        fail("missing " + ", ".join(f"out/dashboard/{n}.json" for n in missing) + ". Run scripts/refresh.py first.")
    rows = json.loads((DATA / "today.json").read_text())["rows"]
    if not rows:
        fail("out/dashboard/today.json has no rows")
    return rows[0]


def dashboard_fragment() -> str:
    """dashboard/index.html without its Claude-only head lines, with PAGE_SWAPS applied."""
    text = (DASH / "index.html").read_text()
    text = re.sub(r"<meta[^>]*>\s*", "", text)
    text = text.replace('<link rel="stylesheet" href="style.css">', "").replace('<script src="app.js"></script>', "")
    if '<div class="brm">' not in text:
        fail('dashboard/index.html no longer contains <div class="brm">')
    for old, new in PAGE_SWAPS:
        if old not in text:
            print(f"  ! dashboard/index.html no longer contains {old[:60]!r}, so it was left as it is")
        text = text.replace(old, new)
    return text.strip()


def writeup() -> tuple[str, list[tuple[str, str]]]:
    """WRITEUP.md as HTML, and its sections as (id, title) for the page's contents list."""
    try:
        import markdown
    except ImportError:
        fail("the markdown package is missing: pip install -r requirements-site.txt")
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = md.convert((ROOT / "WRITEUP.md").read_text())

    def walk(tokens):
        for t in tokens:
            yield t
            yield from walk(t.get("children", []))

    sections = [(t["id"], html.unescape(t["name"])) for t in walk(md.toc_tokens) if t["level"] == 2]

    def fix_link(m: re.Match) -> str:
        href = m.group(1)
        if href.startswith(SITE_URL):                        # a page of this website: stay on this host
            href = href[len(SITE_URL):] or "./"
        elif not re.match(r"^(https?:|mailto:|#)", href):    # a file in the repository
            href = f"{REPO_URL}/blob/main/{href.removeprefix('./')}"
        return f'href="{href}"'

    def short_cells_stay_whole(m: re.Match) -> str:     # "Very low" or "0.0 to 0.2" should not break
        text = html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        return f'<td{m.group(1)} class="nw">{m.group(2)}</td>' if len(text) <= 22 else m.group(0)

    body = re.sub(r'href="([^"]*)"', fix_link, body)
    body = re.sub(r"<td([^>]*)>(.*?)</td>", short_cells_stay_whole, body, flags=re.S)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    return body, sections


def render(template: str, fields: dict[str, str], assets: dict[str, str], current: str) -> str:
    out = template
    for key, value in fields.items():
        out = out.replace("{{" + key + "}}", value)
    out = re.sub(r"\{\{asset:([^}]+)\}\}", lambda m: assets[m.group(1)], out)
    out = re.sub(r"\{\{current:([a-z]+)\}\}", lambda m: ' aria-current="page"' if m.group(1) == current else "", out)
    left = re.findall(r"\{\{[^}]*\}\}", out)
    if left:
        fail(f"unfilled placeholders in site/template.html: {sorted(set(left))}")
    return out


def main() -> int:
    today = load_today()
    risk, zone, day = float(today["risk"]), str(today["zone"]), str(today["date"])
    y, m, d = (int(x) for x in day.split("-"))
    day_text = f"{d} {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1]} {y}"
    version = re.sub(r"[^0-9]", "", str(today.get("built_at", "")))[:12] or day.replace("-", "")

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    for name in FILES:
        shutil.copyfile(DATA / f"{name}.json", OUT / "data" / f"{name}.json")

    # Static files. Each is linked with a short hash of its content, so a browser never keeps an old copy.
    app = (DASH / "app.js").read_text()
    static = {
        "theme.css": (SRC / "theme.css").read_bytes(),
        "shim.js": (SRC / "shim.js").read_bytes(),
        "favicon.svg": (SRC / "favicon.svg").read_bytes(),
        "style.css": (DASH / "style.css").read_bytes(),
        # wrapped in a function so the page code keeps its names to itself, as it does inside Claude
        "app.js": ("(function () {\n" + app + "\n})();\n").encode("utf-8"),
        "vendor/d3.min.js": (SRC / "vendor" / "d3.min.js").read_bytes(),
        "vendor/d3-LICENSE.txt": (SRC / "vendor" / "d3-LICENSE.txt").read_bytes(),
    }
    assets = {}
    for rel, raw in static.items():
        (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
        (OUT / rel).write_bytes(raw)
        assets[rel] = f"{rel}?v={hashlib.sha256(raw).hexdigest()[:10]}"

    template = (SRC / "template.html").read_text()
    blank = {"base": "", "head": "", "scripts": "", "version": version}

    pages = {
        "index.html": render(template, {
            **blank,
            "title": "Bitcoin Risk Metric",
            "description": html.escape(
                f"Today's reading is {risk:.2f}, in the {zone} zone, on data through {day_text}. One number from 0 to 1 "
                "for where bitcoin sits in its market cycle, rebuilt every day from free public data."),
            "url": SITE_URL,
            "head": f'<link rel="stylesheet" href="{assets["style.css"]}">',
            "content": '<p class="site-stale" id="site-stale" role="status" hidden></p>\n' + dashboard_fragment(),
            "scripts": "\n".join(f'<script src="{assets[s]}"></script>' for s in ("vendor/d3.min.js", "shim.js", "app.js")),
        }, assets, current="dashboard"),
    }

    body, sections = writeup()
    toc = "".join(f'<li><a href="#{sid}">{html.escape(name)}</a></li>' for sid, name in sections)
    cut = body.find("<h2")                 # the title and its opening note come before the contents list
    head, rest = (body[:cut], body[cut:]) if cut > 0 else ("", body)
    pages["how-it-works.html"] = render(template, {
        **blank,
        "title": "How it works: Bitcoin Risk Metric",
        "description": html.escape("How the Bitcoin Risk Metric is built, how it was tested over bitcoin's whole "
                                   "history, and where it falls short."),
        "url": SITE_URL + "how-it-works.html",
        "content": ('<article class="doc doc-layout">\n'
                    f'<header class="doc-head">\n{head.strip()}\n</header>\n'
                    f'<nav class="doc-toc" aria-label="On this page"><p class="doc-toc-h">On this page</p><ol>{toc}</ol></nav>\n'
                    f'<div class="doc-body">\n{rest.strip()}\n</div>\n</article>'),
    }, assets, current="how")

    # GitHub Pages shows 404.html for any wrong address, however deep, so its links resolve from the site root.
    pages["404.html"] = render(template, {
        **blank,
        "base": f'<base href="{SITE_URL}">',
        "title": "Page not found: Bitcoin Risk Metric",
        "description": "There is no page at this address.",
        "url": SITE_URL,
        "content": ('<div class="site-404"><h1>Page not found</h1><p>There is nothing at this address. This site has two '
                    'pages: the <a href="./">dashboard</a> and <a href="how-it-works.html">how it works</a>.</p></div>'),
    }, assets, current="")

    for name, text in pages.items():
        (OUT / name).write_text(text)
    (OUT / ".nojekyll").write_text("")   # serve the files as they are, without GitHub's Jekyll step

    # Nothing that only works inside Claude should reach the public pages.
    for name in ("index.html", "how-it-works.html"):
        for needle in ("claude.ai/artifact", "Open Sources"):
            if needle in pages[name]:
                print(f"  ! {name} still mentions {needle!r}")

    files = [p for p in OUT.rglob("*") if p.is_file()]
    print(f"Website built in _site/: {len(files)} files, {sum(p.stat().st_size for p in files) / 1024:.0f} KB")
    print(f"OK  data through {day}  reading {risk:.3f}  zone {zone}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
