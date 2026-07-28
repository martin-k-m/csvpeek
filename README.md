# csvpeek

A fast, **zero-dependency** CSV profiler for the terminal. Point it at a file and get
column types, null counts, numeric statistics, and top values — in one glance.

Pure Python standard library. Deterministic: the same file always produces the same
profile. No pandas, no install-time downloads, nothing leaves your machine.

```
$ csvpeek examples/people.csv

  6 rows × 5 columns

  column  type      nulls  unique  summary
  ─────────────────────────────────────────────────────────────────────
  name    string        0       6  Ann (1), Bob (1), Cara (1), Dan (1), Eve (1)
  age     int      1 (16.7%)     5  min 22 · max 41 · mean 31 · median 29 · sd 6.2929
  city    string        0       3  Santa Cruz (3), Brentwood (2), Oakland (1)
  active  bool          0       2  true (4), false (2)
  score   float    1 (16.7%)     5  min 6.5 · max 9.4 · mean 8.16 · median 8.8 · sd 1.143
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
csvpeek data.csv --json          # machine-readable output
csvpeek data.csv --no-color      # plain text
```

| Flag | Description |
| :-- | :-- |
| `-d`, `--delimiter` | Field delimiter (default `,`) |
| `-t`, `--top N` | Show top *N* values for text columns (default 5) |
| `--json` | Emit the full profile as JSON |
| `--no-color` | Disable colored output |
| `-V`, `--version` | Print version |

## What it computes

- **Type inference** per column — `int`, `float`, `bool`, `string`, or `empty`. A column
  is numeric only if *every* non-null value parses; one stray label keeps it a string
  (no silent coercion).
- **Nulls** — empty, `NA`, `N/A`, `null`, `none`, `nan`, `nil` (case-insensitive), with a
  percentage.
- **Numeric columns** — min, max, mean, median, and population standard deviation.
- **Text/bool columns** — unique count and the most common values (ties broken
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

## Development

```sh
pip install pytest .
pytest -q
```

## License

MIT © Martin Muskov
