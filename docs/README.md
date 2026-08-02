# csvpeek documentation

csvpeek profiles a CSV from the terminal: column types, null counts, numeric
statistics, and top values. Pure Python standard library, zero dependencies, and
deterministic — the same file always produces the same profile.

| Document | What it covers |
| :-- | :-- |
| [cli.md](cli.md) | Every flag, output format, and exit code |
| [profiling.md](profiling.md) | The exact rules behind every number csvpeek prints |
| [api.md](api.md) | Using csvpeek as a library |

The [README](../README.md) is the fastest way in; these pages are the reference.

## Design commitments

These are the properties the project holds itself to. They are worth knowing
before you rely on the output for anything.

- **Deterministic.** No sampling, no randomness, no hash-order dependence. Ties
  in "top values" break alphabetically so repeated runs are byte-identical.
- **No silent coercion.** A column takes a type only if *every* non-null value
  fits it. One stray label keeps the column a `string` rather than quietly
  dropping the values that do not parse.
- **Explainable.** Every statistic is something you could compute by hand from
  the column. [profiling.md](profiling.md) gives the precise definition of each.
- **Offline.** csvpeek opens one file and prints to stdout. Nothing is uploaded,
  cached, or phoned home, and there is no install-time download.
