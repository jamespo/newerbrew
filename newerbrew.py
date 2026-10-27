#!/usr/bin/env python3
"""Generate RSS feeds for Homebrew.

Three feeds are produced:

* ``new``     - software newly introduced to Homebrew since the last run, i.e.
                packages that were not present in the previous snapshot.
* ``updated`` - existing packages that have been bumped to a new version since
                the last run.
* ``random``  - a handful of randomly chosen packages, for discovering projects
                you might not otherwise stumble across.

State for ``new`` and ``updated`` is tracked in a small JSON snapshot so the
feeds reflect genuine changes between invocations.

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

def load_snapshot(snapshot_path: Path) -> dict[str, str]:
    """Load the saved name -> version map, or empty if there is none yet."""
    if snapshot_path.exists():
        return json.loads(snapshot_path.read_text())
    return {}


def save_snapshot(current: dict[str, dict], snapshot_path: Path) -> None:
    """Persist the current name -> version map for the next run."""
    snapshot = {name: pkg["version"] for name, pkg in current.items()}
    snapshot_path.write_text(json.dumps(snapshot, sort_keys=True))


def build_new_feed(current: dict[str, dict], previous: dict[str, str]) -> str:
    """Emit packages newly introduced to Homebrew since the last snapshot."""
    items: list[str] = []
    if previous:
        for name, pkg in sorted(current.items()):
            if name not in previous:
                title = f"New {pkg['kind']}: {name} {pkg['version']}"
                desc = pkg["desc"] or "Newly added to Homebrew."
                items.append(rss_item(pkg, title, desc))

    description = (
        "Software newly added to Homebrew since the last check."
        if previous
        else "Newly added Homebrew packages. Baseline captured; "
        "new software will appear on the next run."
    )
    return render_feed(
        "Homebrew: New Packages",
        "https://formulae.brew.sh",
        description,
        items,
    )


def build_updated_feed(current: dict[str, dict], previous: dict[str, str]) -> str:
    """Emit existing packages that were bumped to a new version."""
    items: list[str] = []
    if previous:
        for name, pkg in sorted(current.items()):
            old = previous.get(name)
            if old is not None and old != pkg["version"]:
                title = f"{name} updated: {old} -> {pkg['version']}"
                desc = pkg["desc"] or f"Bumped from {old} to {pkg['version']}."
                items.append(rss_item(pkg, title, desc))

    description = (
        "Existing Homebrew packages bumped to a new version since the last check."
        if previous
        else "Updated Homebrew packages. Baseline captured; "
        "version bumps will appear on the next run."
    )
    return render_feed(
        "Homebrew: Updated Packages",
        "https://formulae.brew.sh",
        description,
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
        choices=["new", "updated", "random", "all"],
        help="Which feed to generate ('all' generates every feed).",
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

    previous = load_snapshot(snapshot_path)

    if args.feed in ("new", "all"):
        xml = build_new_feed(current, previous)
        path = args.outdir / "new.xml"
        path.write_text(xml)
        print(f"Wrote {path}", file=sys.stderr)

    if args.feed in ("updated", "all"):
        xml = build_updated_feed(current, previous)
        path = args.outdir / "updated.xml"
        path.write_text(xml)
        print(f"Wrote {path}", file=sys.stderr)

    if args.feed in ("random", "all"):
        xml = build_random_feed(current, args.count)
        path = args.outdir / "random.xml"
        path.write_text(xml)
        print(f"Wrote {path}", file=sys.stderr)

    # Persist the snapshot once, after every feed has diffed against it.
    if args.feed in ("new", "updated", "all"):
        save_snapshot(current, snapshot_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
