# Library API

Everything the CLI does is available as a small, dependency-free API. The
functions are pure: they read a file, or accept rows you already have, and return
dataclasses. Nothing is cached or mutated globally.

```python
from csvpeek import profile_file

profile = profile_file("data.csv")
print(profile.rows)

for col in profile.columns:
    print(col.name, col.dtype, col.nulls, col.mean)
```

## Functions

### `profile_file(path, delimiter=None, top_n=5, limit=None) -> Profile`

Read and profile a CSV file.

| Argument | Meaning |
| :-- | :-- |
| `path` | Path to the file. Opened as `utf-8-sig` |
| `delimiter` | Field delimiter. `None` auto-detects, see [profiling.md](profiling.md#reading-the-file) |
| `top_n` | How many most-common values to keep per non-numeric column |
| `limit` | Read only the first N data rows. `None` reads everything |

Raises `FileNotFoundError` if the path does not exist, and `OSError` for other
read failures. Raises [`ProfileError`](#profileerror) if the file opens but
cannot be profiled: the bytes are not UTF-8, the CSV reader refuses them, or a
numeric column holds a non-finite value. A file with no header row returns
`Profile(rows=0, columns=[])`.

### `profile_rows(header, rows, top_n=5, limit=None) -> Profile`

Profile rows you have already parsed. `header` is a sequence of column names and
`rows` is any iterable of sequences: a `csv.reader`, a list of lists, or a
generator. Use this when the data is not a file on disk.

Raises [`ProfileError`](#profileerror) if a numeric column contains a value that
is not finite.

### `infer_type(values) -> str`

Infer a column type from a sequence of raw string values, returning one of
`empty`, `bool`, `int`, `float`, `date`, `string`. Nulls are excluded internally,
so pass the column as it appears in the file.

### `is_null(value) -> bool`

Whether a single raw string counts as missing. Strips and lowercases before
comparing against `NULL_TOKENS`.

### `sniff_delimiter(sample) -> str`

Guess a delimiter from a text sample, considering `,` `;` tab and `|`, falling
back to `,` when detection fails.

### `NULL_TOKENS`

The frozen set of strings treated as missing. Exported so you can check what
csvpeek considers null rather than reimplementing the list.

### `SCHEMA_VERSION`

The `int` that `to_dict()` writes as `"schema"`. Importable from `csvpeek`, so
code that writes a profile to disk can record the version it produced without
hard-coding a number.

## Types

### `ProfileError`

Raised when the input is readable but cannot be profiled. It is a plain
`Exception`, deliberately not an `OSError`: the file opened fine and its
*contents* are the problem, which is a different thing to react to. The message
says which file or column, and why.

```python
from csvpeek import ProfileError, profile_file

try:
    profile = profile_file("export.csv")
except ProfileError as exc:
    print(f"skipping: {exc}")
```

### `Profile`

| Attribute | Type | Meaning |
| :-- | :-- | :-- |
| `rows` | `int` | Number of data rows read, excluding the header, respecting `limit` |
| `columns` | `list[ColumnProfile]` | One per header field, in file order |
| `to_dict()` | `dict` | JSON-ready form, see below |

### `ColumnProfile`

| Attribute | Type | Present for |
| :-- | :-- | :-- |
| `name` | `str` | all |
| `dtype` | `str` | all |
| `count` | `int` | all, non-null values |
| `nulls` | `int` | all |
| `unique` | `int` | all, distinct non-null values |
| `null_pct` | `float` (property) | all, percentage to one decimal |
| `minimum`, `maximum` | `int \| float \| None` | numeric only |
| `median` | `int \| float \| None` | numeric only |
| `mean`, `stdev` | `float \| None` | numeric only |
| `p25`, `p75` | `float \| None` | numeric with ≥2 values |
| `top` | `list[tuple[str, int]]` | non-numeric, `(value, count)` |

Fields that do not apply to a column are `None`, or `[]` for `top`, never zero.
`None` means *not applicable*, so treating it as `0` will silently invent data.
Check `dtype` first.

An `int` column answers with `int`s wherever it can do so exactly, so `minimum`
and `maximum` are `int`s there, and so is `median` when the count is odd. See
[profiling.md](profiling.md#statistics) for the rule and its one edge case.

## JSON shape

`Profile.to_dict()` is what `--json` prints: a schema version, then the profile.
Every column key is named exactly as the attribute it comes from.

```json
{
  "schema": 1,
  "rows": 6,
  "columns": [
    {
      "name": "age",
      "dtype": "int",
      "count": 5,
      "nulls": 1,
      "null_pct": 16.7,
      "unique": 4,
      "minimum": 22,
      "maximum": 41,
      "mean": 31.0,
      "median": 29,
      "stdev": 6.2929,
      "p25": 25.5,
      "p75": 37.5,
      "top": []
    }
  ]
}
```

`top` is the one field that changes shape, from `(value, count)` pairs to
`{"value": ..., "count": ...}` objects, because JSON has no tuple.
Non-applicable numeric fields serialise as `null`. This shape is the stable
contract, so parse it rather than the table output.

### `schema`

The top-level `schema` is an integer, currently `1`, and it is the first thing to
read. It goes up whenever a key is renamed, removed, or changes meaning, so a
consumer can reject a payload it does not understand instead of finding out one
missing field at a time. Adding an optional key does not bump it, so parse
leniently: check `schema`, then ignore any key you do not recognise.

```python
import json

from csvpeek import SCHEMA_VERSION

with open("profile.json") as fh:
    payload = json.load(fh)

if payload["schema"] != SCHEMA_VERSION:
    raise SystemExit(f"profile.json is schema {payload['schema']}, not {SCHEMA_VERSION}")
```

> **Changed before 1.0.** `minimum` and `maximum` used to be emitted as `min` and
> `max`, and every numeric statistic was a float, so an `int` column reported
> `"min": 22.0` alongside `"dtype": "int"`. Both are fixed above, and `schema`
> exists so the next such change is detectable rather than silent.
