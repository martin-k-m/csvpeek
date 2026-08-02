# csvpeek

[![CI](https://github.com/martin-k-m/csvpeek/actions/workflows/ci.yml/badge.svg)](https://github.com/martin-k-m/csvpeek/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/martin-k-m/csvpeek?sort=semver&display_name=tag&label=release&color=7C6CFF)](https://github.com/martin-k-m/csvpeek/releases/latest)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-7C6CFF)](LICENSE)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-4F8CFF)](pyproject.toml)

A fast, **zero-dependency** CSV profiler for the terminal. Point it at a file and get
column types, null counts, numeric statistics, and top values, in one glance.

Pure Python standard library. Deterministic: the same file always produces the same
profile. No pandas, no install-time downloads, nothing leaves your machine.

```
$ csvpeek examples/people.csv

  6 rows × 5 columns

  column  type      nulls  unique  summary
  ────────────────────────────────────────
  name    string        0       6  Ann (1), Bob (1), Cara (1), Dan (1), Eve (1)
  age     int     1 (16.7%)       4  min 22 · p25 25.5 · median 29 · p75 37.5 · max 41 · mean 31 · sd 6.2929
  city    string        0       3  Santa Cruz (3), Brentwood (2), Oakland (1)
  active  bool          0       2  true (4), false (2)
  score   float   1 (16.7%)       5  min 6.5 · p25 6.8 · median 8.8 · p75 9.2 · max 9.4 · mean 8.16 · sd 1.143
```

## Install

Requires Python 3.9+.

```sh
pip install git+https://github.com/martin-k-m/csvpeek
```

Or run it straight from a clone, no install needed:

```sh
python -m csvpeek data.csv
```

## Usage

```sh
csvpeek data.csv                 # profile a CSV
csvpeek data.tsv -d $'\t'        # tab-separated
csvpeek data.csv --top 10        # more top values for text columns
csvpeek big.csv -n 10000         # sample the first 10k rows of a large file
csvpeek data.csv --format md     # a Markdown table to paste into a PR
csvpeek data.csv --json          # machine-readable output
csvpeek data.csv --no-color      # plain text
```

| Flag | Description |
| :-- | :-- |
| `-d`, `--delimiter` | Field delimiter (default: auto-detect `,` `;` tab `\|`) |
| `-t`, `--top N` | Show top *N* values for text columns (default 5) |
| `-n`, `--limit ROWS` | Only read the first *ROWS* data rows (sample large files) |
| `--format {table,md,json}` | Output format: `table` (default), `md` (Markdown), or `json` |
| `--json` | Shortcut for `--format json` |
| `--no-color` | Disable colored output |
| `-V`, `--version` | Print version |

## What it computes

- **Type inference** per column: `int`, `float`, `bool`, `date`, `string`, or `empty`. A
  column takes a type only if *every* non-null value fits; one stray label keeps it a
  string (no silent coercion). Dates require a separator (`2024-01-01`, `01/02/2024`), so
  bare years and ids stay numeric.
- **Nulls**: empty, `NA`, `N/A`, `null`, `none`, `nan`, `nil` (case-insensitive), with a
  percentage.
- **Numeric columns**: min, 25th/50th/75th percentiles, max, mean, and population
  standard deviation.
- **Text/bool columns**: unique count and the most common values (ties broken
  alphabetically, so runs are reproducible).

## Library

Everything the CLI does is available as a small API:

```python
from csvpeek import profile_file

profile = profile_file("data.csv")
print(profile.rows)
for col in profile.columns:
    print(col.name, col.dtype, col.nulls, col.mean)

profile.to_dict()   # JSON-ready
```

## Documentation

| Document | What it covers |
| :-- | :-- |
| [docs/cli.md](docs/cli.md) | Every flag, output format, and exit code |
| [docs/profiling.md](docs/profiling.md) | The exact rules behind every number csvpeek prints |
| [docs/api.md](docs/api.md) | Using csvpeek as a library |

## Development

```sh
pip install pytest .
pytest -q
```

## License

MIT © Martin Muskov
