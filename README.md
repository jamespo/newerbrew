# newerbrew

Generate RSS feeds for [Homebrew](https://brew.sh) packages. Inspired by
[atheken/newbrew](https://github.com/atheken/newbrew).

Three feeds are produced:

- **`new`** — software **newly introduced** to Homebrew since the last run,
  i.e. formulae (and optionally casks) that weren't present before.
- **`updated`** — existing packages that were **bumped to a new version**
  since the last run.
- **`random`** — a handful of randomly chosen packages, for discovering
  projects you might not otherwise stumble across.

Uses only the Python standard library — there is nothing to `pip install`.
Requires Python 3.10+.

## Usage

```bash
python3 newerbrew.py all                  # generate every feed
python3 newerbrew.py new                  # just newly introduced packages
python3 newerbrew.py updated              # just version bumps
python3 newerbrew.py random --count 20    # 20 random packages
python3 newerbrew.py all --casks          # include casks as well as formulae
python3 newerbrew.py all -o ./public      # write feeds + snapshot elsewhere
```

### Options

| Option            | Default            | Description                                        |
| ----------------- | ------------------ | -------------------------------------------------- |
| `feed`            | (required)         | One of `new`, `updated`, `random`, or `all`.       |
| `-o`, `--outdir`  | `.`                | Directory to write the feed XML into.              |
| `--snapshot PATH` | `<outdir>/snapshot.json` | Where the version snapshot is stored.        |
| `--count N`       | `15`               | Number of packages in the random feed.             |
| `--casks`         | off                | Include casks in addition to formulae.             |

## How the `new` and `updated` feeds work

The script fetches the full package list from Homebrew's public JSON API and
compares it against a saved snapshot (`snapshot.json`). Packages absent from the
snapshot become `new` feed items; packages present but at a different version
become `updated` feed items. The snapshot is then rewritten for the next run.

The **first run** has nothing to diff against, so it captures a baseline and
emits empty feeds rather than dumping every package. Changes appear from the
second run onward. For a live feed, run it on a schedule with a stable
`--snapshot` path so state persists:

```cron
# Refresh feeds every hour
0 * * * * cd /path/to/newerbrew && python3 newerbrew.py all -o ./public
```

## Output

- `new.xml` / `updated.xml` / `random.xml` — RSS 2.0 feeds.
- `snapshot.json` — version state used to diff the `new` and `updated` feeds
  between runs.

These are generated artifacts and are git-ignored.

## Data source

- Formulae: <https://formulae.brew.sh/api/formula.json>
- Casks: <https://formulae.brew.sh/api/cask.json>
