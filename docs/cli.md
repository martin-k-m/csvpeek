# CLI reference

```
csvpeek [options] FILE
```

Profiles `FILE` and prints the result. `FILE` is required and positional. Pass
`-` to read the CSV from standard input instead of a path, so csvpeek fits into a
pipe: `cat data.csv | csvpeek -`. Detection, delimiter sniffing and every flag
work the same on stdin as on a file.

If csvpeek is not on your `PATH`, `python -m csvpeek` is equivalent and needs no
installation.

## Options

| Flag | Default | Description |
| :-- | :-- | :-- |
| `-d`, `--delimiter CHAR` | auto-detect | Field delimiter. Auto-detection considers `,` `;` tab and `\|` |
| `-t`, `--top N` | `5` | How many of the most common values to show for text and bool columns |
| `-n`, `--limit ROWS` | all | Read only the first `ROWS` data rows. The header is always read |
| `-c`, `--columns A,B,C` | all | Profile only these columns, comma-separated, in the order given |
| `--format {table,md,json}` | `table` | Output format |
| `--json` | off | Shortcut for `--format json` |
| `--no-color` | off | Disable ANSI colour |
| `-V`, `--version` | | Print the version and exit |
| `-h`, `--help` | | Print usage and exit |

`--json` wins over `--format` if both are given.

## Selecting columns

`-c/--columns` restricts the profile to the columns you name, comma-separated,
and prints them in the order you give rather than file order. Whitespace around a
name is trimmed, so `--columns "a, b"` and `--columns a,b` mean the same thing. A
name that is not in the header stops csvpeek with an error naming the missing
column and listing what is available, and exits `3`. Passing only empty names,
such as `--columns " , "`, is a usage error and exits `2`.

Row counting is unchanged: selection narrows the columns, not the rows, so `rows`
and each column's `count` are the same numbers a full profile would report.

```sh
csvpeek data.csv --columns age,city         # just two columns, in that order
csvpeek data.csv --json -c amount           # one column as JSON
```

## Output formats

**`table`** is the default: an aligned terminal table. Colour is applied only
when stdout is a TTY *and* `--no-color` was not passed, so a redirect or a pipe
gets plain text automatically. You rarely need `--no-color` explicitly.

**`md`** is a Markdown document with a table, intended for pasting into a pull
request or an issue. Column names are backticked, and `|` and `\` in names or
values are escaped so a stray character cannot break the table.

**`json`** is the full profile, indented two spaces. This is the format to parse.
The table layout is for humans and may change. The payload opens with a
`"schema"` number, currently `1`, which goes up if a key is ever renamed or
changes meaning, so check it before trusting the rest. See
[api.md](api.md#json-shape) for the full schema.

### Numeric histogram

Every `int` and `float` column carries a small histogram: its values bucketed
into ten evenly spaced bins (one bin when every value is identical). The `table`
and `md` output render it as a one-row sparkline appended to the numeric summary,
after `sd`:

```
v  int  0  10  min 1 · … · sd 3.2326 · hist █▅▃▁▃▁▁▁▃▃
```

Bar heights are relative to the fullest bin, so the tallest bar is the busiest
bin and a flat row means the bins are even, not that the column is empty. The
sparkline uses the block characters `▁▂▃▄▅▆▇█`, and falls back to `.:-=+*#@` on a
console that cannot encode them, the same way the rest of the table degrades.

`--json` reports the histogram as an object with `edges` and `counts` under a
`"histogram"` key on each column: an object for a numeric column, `null` for the
rest. `edges` has one more entry than `counts`; `edges[i]` and `edges[i+1]` bound
bin `i`, half-open except the last bin, whose top edge is closed so the maximum
value is counted rather than dropped. The key is additive, so `schema` stays `1`
and a consumer that does not know the key can ignore it. Nulls and the non-finite
guard are respected: the same values that feed the statistics feed the bins.

### Characters and encoding

`table` and `md` use three non-ASCII characters: `─` for the rule, `×` between
the row and column counts, and `·` between statistics. csvpeek asks stdout what
it can encode before printing, and swaps all three for `-`, `x` and `|` when the
answer is no. A cp1252 console, which is the Windows default without
`PYTHONUTF8=1`, therefore gets a plain ASCII table rather than a crash, and a
Markdown file written there is ASCII rather than mojibake. Set `PYTHONUTF8=1` or
`PYTHONIOENCODING=utf-8` to keep the original characters.

Values and column names come from the file and can be anything. Those the stream
cannot encode are escaped as `\uXXXX` instead of ending the run, so the value is
still visible even on a console that cannot draw it. `json` output is ASCII-only
in every case.

## Examples

```sh
csvpeek data.csv                  # profile a CSV
cat data.csv | csvpeek -          # read from standard input
csvpeek data.tsv -d $'\t'         # tab-separated
csvpeek export.csv -d ';'         # semicolon-separated
csvpeek data.csv --top 10         # more top values for text columns
csvpeek big.csv -n 10000          # sample the first 10k data rows
csvpeek data.csv --columns a,b    # profile only columns a and b, in that order
csvpeek data.csv --format md      # Markdown table for a PR
csvpeek data.csv --json | jq '.columns[] | select(.nulls > 0) | .name'
```

That last one is the pattern worth remembering. `--json` plus `jq` turns csvpeek
into a check you can run in CI, for example failing a build when a column that
should be complete has gone sparse.

## Exit codes

| Code | Meaning |
| ---: | :-- |
| `0` | The file was profiled and the result printed |
| `2` | The file does not exist, or could not be read |
| `2` | Invalid arguments (argparse) |
| `3` | The file was read, but its contents cannot be profiled |

Exit `3` covers these cases, each reported on stderr with the reason:

- the bytes are not UTF-8, for example a spreadsheet saved as cp1252
- Python's CSV reader refuses the file, most often a field past its 131072-byte
  size limit
- a numeric column contains a value that is not finite, such as `inf` or an
  integer too large to hold as a float
- a numeric column is finite but cannot be summarised: values near the top of the
  float range overflow when summed, and a column holding both `1e308` and
  `-1e308` has an infinite spread, so its quartiles are infinite
- `-d/--delimiter` was given something other than a single character
- `-c/--columns` named a column the header does not contain

The last two matter for `--json` in particular. There is no JSON literal for
infinity, so emitting one would hand `jq` output it refuses to parse while the
exit code still said everything was fine.

`1` is left to mean csvpeek itself fell over, so a check that treats a non-zero
exit as failure can still tell a bad file apart from a bug.

Most malformed CSV is not an error. csvpeek reads what is there: rows shorter
than the header are padded with empty values, which then count as nulls. A file
whose header row is missing entirely, meaning a completely empty file, profiles
as zero rows and zero columns rather than failing.

## Sampling large files

`-n/--limit` stops reading after N data rows. It is a genuine early exit, not a
filter applied after loading, so it is the right tool for a multi-gigabyte file.

Be aware of what it changes. Every statistic is then computed over the sample,
not the file. Type inference in particular can differ: if the one non-numeric
value in a column sits at row 50,000, then `-n 10000` reports that column as
`int` where a full read reports `string`. Sample to explore, then read fully
before you conclude anything.
