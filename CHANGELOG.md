# Changelog

All notable changes to csvpeek are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
