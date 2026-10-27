#!/usr/bin/env python3
"""Generate RSS feeds for Homebrew.

Two feeds are produced:

* ``new``    - formulae that were added or bumped to a new version since the
               last run. State is tracked in a small JSON snapshot so the feed
               reflects genuine changes between invocations.
* ``random`` - a handful of randomly chosen formulae, for discovering projects
               you might not otherwise stumble across.

Inspired by https://github.com/atheken/newbrew. Uses only the standard library,
so there is nothing to ``pip install``.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

FORMULA_API = "https://formulae.brew.sh/api/formula.json"
CASK_API = "https://formulae.brew.sh/api/cask.json"
FORMULA_PAGE = "https://formulae.brew.sh/formula/{name}"
CASK_PAGE = "https://formulae.brew.sh/cask/{name}"
USER_AGENT = "newerbrew/1.0 (+https://github.com/atheken/newbrew)"


def fetch(url: str) -> list[dict]:
    """Fetch and parse a Homebrew JSON API endpoint."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def version_of(pkg: dict) -> str:
    """Best-effort current version string for a formula or cask."""
    versions = pkg.get("versions")
    if isinstance(versions, dict) and versions.get("stable"):
        return str(versions["stable"])
    # Casks expose a plain "version" field instead.
    if pkg.get("version"):
        return str(pkg["version"])
    return "unknown"


def normalize(packages: list[dict], kind: str) -> dict[str, dict]:
    """Reduce the raw API payload to the fields we care about, keyed by name."""
    page = FORMULA_PAGE if kind == "formula" else CASK_PAGE
    out: dict[str, dict] = {}
    for pkg in packages:
        name = pkg.get("token") or pkg.get("name")
        if not name:
            continue
        desc = pkg.get("desc") or (pkg.get("name") if kind == "cask" else "")
        out[name] = {
            "name": name,
            "kind": kind,
            "version": version_of(pkg),
            "desc": desc or "",
            "homepage": pkg.get("homepage", ""),
            "url": page.format(name=name),
        }
    return out


# --------------------------------------------------------------------------- #
# RSS rendering
# --------------------------------------------------------------------------- #

def rss_item(pkg: dict, title: str, description: str) -> str:
    link = escape(pkg["url"])
    guid = f"{link}#{escape(pkg['version'])}"
    pubdate = format_datetime(datetime.now(timezone.utc))
    return (
        "    <item>\n"
        f"      <title>{escape(title)}</title>\n"
        f"      <link>{link}</link>\n"
        f"      <guid isPermaLink=\"false\">{guid}</guid>\n"
        f"      <pubDate>{pubdate}</pubDate>\n"
        f"      <description>{escape(description)}</description>\n"
        "    </item>"
    )


def render_feed(title: str, link: str, description: str, items: list[str]) -> str:
    built = format_datetime(datetime.now(timezone.utc))
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        f"    <title>{escape(title)}</title>\n"
        f"    <link>{escape(link)}</link>\n"
        f"    <description>{escape(description)}</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{built}</lastBuildDate>\n"
        f"{body}\n"
        "  </channel>\n"
        "</rss>\n"
    )


# --------------------------------------------------------------------------- #
# Feed builders
# --------------------------------------------------------------------------- #

def build_new_feed(current: dict[str, dict], snapshot_path: Path) -> str:
    """Compare against the saved snapshot and emit added/updated packages."""
    previous: dict[str, str] = {}
    if snapshot_path.exists():
        previous = json.loads(snapshot_path.read_text())

    items: list[str] = []
    for name, pkg in sorted(current.items()):
        old = previous.get(name)
        if old is None:
            title = f"New {pkg['kind']}: {name} {pkg['version']}"
            desc = pkg["desc"] or "Newly added to Homebrew."
            items.append(rss_item(pkg, title, desc))
        elif old != pkg["version"]:
            title = f"{name} updated: {old} -> {pkg['version']}"
            desc = pkg["desc"] or f"Bumped from {old} to {pkg['version']}."
            items.append(rss_item(pkg, title, desc))

    # Persist the new snapshot for the next run.
    snapshot = {name: pkg["version"] for name, pkg in current.items()}
    snapshot_path.write_text(json.dumps(snapshot, sort_keys=True))

    if not previous:
        # First run: nothing to diff against, so don't flood the feed.
        return render_feed(
            "Homebrew: New & Updated",
            "https://formulae.brew.sh",
            "Formulae and casks added or updated. Baseline captured; "
            "changes will appear on the next run.",
            [],
        )

    return render_feed(
        "Homebrew: New & Updated",
        "https://formulae.brew.sh",
        "Formulae and casks added or updated since the last check.",
        items,
    )


def build_random_feed(current: dict[str, dict], count: int) -> str:
    chosen = random.sample(list(current.values()), min(count, len(current)))
    items = [
        rss_item(
            pkg,
            f"{pkg['name']} {pkg['version']}",
            pkg["desc"] or "A Homebrew package worth a look.",
        )
        for pkg in chosen
    ]
    return render_feed(
        "Homebrew: Random Projects",
        "https://formulae.brew.sh",
        "A random selection of Homebrew packages to discover.",
        items,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "feed",
        choices=["new", "random", "both"],
        help="Which feed to generate.",
    )
    parser.add_argument(
        "-o", "--outdir",
        type=Path,
        default=Path("."),
        help="Directory to write feed XML into (default: current dir).",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Path to the version snapshot JSON (default: <outdir>/snapshot.json).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=15,
        help="Number of packages in the random feed (default: 15).",
    )
    parser.add_argument(
        "--casks",
        action="store_true",
        help="Include casks in addition to formulae.",
    )
    args = parser.parse_args(argv)

    args.outdir.mkdir(parents=True, exist_ok=True)
    snapshot_path = args.snapshot or (args.outdir / "snapshot.json")

    print("Fetching Homebrew formulae...", file=sys.stderr)
    current = normalize(fetch(FORMULA_API), "formula")
    if args.casks:
        print("Fetching Homebrew casks...", file=sys.stderr)
        current.update(normalize(fetch(CASK_API), "cask"))
    print(f"Loaded {len(current)} packages.", file=sys.stderr)

    if args.feed in ("new", "both"):
        xml = build_new_feed(current, snapshot_path)
        path = args.outdir / "new.xml"
        path.write_text(xml)
        print(f"Wrote {path}", file=sys.stderr)

    if args.feed in ("random", "both"):
        xml = build_random_feed(current, args.count)
        path = args.outdir / "random.xml"
        path.write_text(xml)
        print(f"Wrote {path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
