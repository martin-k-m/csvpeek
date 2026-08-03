# Changelog

All notable changes to csvpeek are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-08-03

The JSON output is versioned and self-consistent, and every input csvpeek cannot summarise now fails with a reason instead of a traceback.

### Changed
- **Breaking (JSON).** `--json` and `Profile.to_dict()` emit `minimum` and
  `maximum` where they used to emit `min` and `max`. Those were the only two keys
  that did not match the attribute behind them, and the docs described the rename
  instead of removing it. Readers of `.min`/`.max` need `.minimum`/`.maximum`.
  The dataclass attributes and the table output are unchanged.
- **Breaking (JSON).** An `int` column reports `minimum`, `maximum`, and `median`
  for an odd count, as integers. Every numeric value was cast through `float`, so
  a file saying `2` came back as `"min": 2.0` beside `"dtype": "int"` in the same
  payload. `mean`, `stdev`, `p25` and `p75` divide, so they stay floats for every
  column, as does an even count's `median`.

### Fixed
- Statistics computed from finite values are now checked for finiteness too. A
  column of values near the float maximum overflowed inside `fsum` and escaped as
  a traceback, and a column spanning `1e308` to `-1e308` produced infinite
  quartiles that went into `--json` as bare `Infinity`, which no strict parser
  accepts, at exit 0.
- `-d ";;"` is reported as a user error rather than raising `TypeError` from
  inside the CSV reader.
- Closing the pipe early, as in `csvpeek --json | head -1`, exits quietly instead
  of printing a `BrokenPipeError` traceback.
- Default table output no longer dies with `UnicodeEncodeError` on a console that
  cannot encode its box characters, which is any Windows console without
  `PYTHONUTF8=1`. csvpeek now checks what stdout can encode and falls back to
  `-`, `x` and `|`. The same check applies to `--format md`, which previously
  wrote `×` and `·` as cp1252 bytes into a file everything else reads as UTF-8.
- Values and column names the output stream cannot encode are escaped as
  `\uXXXX` instead of aborting the run.

### Added
- A top-level `"schema"` number in the JSON payload, `1` for the shape described
  in `docs/api.md`, also exported as `csvpeek.SCHEMA_VERSION`. It goes up when a
  key is renamed, removed, or changes meaning, so a consumer can detect a format
  change up front rather than one missing field at a time.
- Exit code `3` for a file that reads but cannot be profiled: not UTF-8, refused
  by the CSV reader (a field past the 131072-byte limit), or a numeric column
  holding a non-finite value such as `inf`. Each prints a readable reason on
  stderr. All three previously escaped as a traceback and exit `1`, which is now
  left to mean csvpeek itself failed.
- `ProfileError`, raised by `profile_file` and `profile_rows` for the same three
  cases, so library callers can catch them without matching on `_csv.Error` or
  `AttributeError`.

## [0.2.0] - 2026-08-02

### Added
- **Markdown output** (`--format md`) renders the profile as a Markdown table you
  can paste straight into a pull request or doc. `--format` also accepts `table`
  (default) and `json`; `--json` is now a shortcut for `--format json`.
- Date-type detection (`date` dtype), separator-guarded so bare years/ids stay numeric.
- `-n`/`--limit` flag to sample only the first N rows of large files.
- Quartiles (25th/75th percentile) for numeric columns.
- Delimiter auto-detection (`,` `;` tab `|`) when `-d` is omitted.
- Ships type information (PEP 561 `py.typed`).

## [0.1.0]

Initial release.

### Added
- Per-column type inference: `int`, `float`, `bool`, `string`, `empty`.
- Null detection (`NA`, `null`, `nan`, …) with percentages.
- Numeric summaries: min, max, mean, median, population standard deviation.
- Top values for text/bool columns (deterministic, ties broken alphabetically).
- `--json` machine-readable output and a small importable API.
- Colored terminal output with `--no-color`.
