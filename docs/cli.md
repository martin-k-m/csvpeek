# CLI reference

```
csvpeek [options] FILE
```

Profiles `FILE` and prints the result. `FILE` is required and positional.

If csvpeek is not on your `PATH`, `python -m csvpeek` is equivalent and needs no
installation.

## Options

| Flag | Default | Description |
| :-- | :-- | :-- |
| `-d`, `--delimiter CHAR` | auto-detect | Field delimiter. Auto-detection considers `,` `;` tab and `\|` |
| `-t`, `--top N` | `5` | How many of the most common values to show for text and bool columns |
| `-n`, `--limit ROWS` | all | Read only the first `ROWS` data rows. The header is always read |
| `--format {table,md,json}` | `table` | Output format |
| `--json` | — | Shortcut for `--format json` |
| `--no-color` | — | Disable ANSI colour |
| `-V`, `--version` | — | Print the version and exit |
| `-h`, `--help` | — | Print usage and exit |

`--json` wins over `--format` if both are given.

## Output formats

**`table`** (default) — an aligned terminal table. Colour is applied only when
stdout is a TTY *and* `--no-color` was not passed, so a redirect or a pipe gets
plain text automatically. You rarely need `--no-color` explicitly.

**`md`** — a Markdown document with a table, intended for pasting into a pull
request or an issue. Column names are backticked, and `|` and `\` in names or
values are escaped so a stray character cannot break the table.

**`json`** — the full profile, indented two spaces. This is the format to parse;
the table layout is for humans and may change. See [api.md](api.md#json-shape)
for the schema.

## Examples

```sh
csvpeek data.csv                  # profile a CSV
csvpeek data.tsv -d $'\t'         # tab-separated
csvpeek export.csv -d ';'         # semicolon-separated
csvpeek data.csv --top 10         # more top values for text columns
csvpeek big.csv -n 10000          # sample the first 10k data rows
csvpeek data.csv --format md      # Markdown table for a PR
csvpeek data.csv --json | jq '.columns[] | select(.nulls > 0) | .name'
```

That last one is the pattern worth remembering: `--json` plus `jq` turns csvpeek
into a check you can run in CI, for example failing a build when a column that
should be complete has gone sparse.

## Exit codes

| Code | Meaning |
| ---: | :-- |
| `0` | The file was profiled and the result printed |
| `2` | The file does not exist, or could not be read |
| `2` | Invalid arguments (argparse) |

A malformed CSV is not an error. csvpeek reads what is there: rows shorter than
the header are padded with empty values, which then count as nulls. A file whose
header row is missing entirely — a completely empty file — profiles as zero rows
and zero columns rather than failing.

## Sampling large files

`-n/--limit` stops reading after N data rows. It is a genuine early exit, not a
filter applied after loading, so it is the right tool for a multi-gigabyte file.

Be aware of what it changes: every statistic is then computed over the sample,
not the file. Type inference in particular can differ — if the one non-numeric
value in a column sits at row 50,000, then `-n 10000` reports that column as
`int` where a full read reports `string`. Sample to explore; read fully before
you conclude anything.
