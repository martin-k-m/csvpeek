# How profiling works

Every number csvpeek prints is defined here. Nothing is estimated or sampled
unless you ask for `--limit`, and nothing depends on iteration order, so two runs
over the same file produce identical output.

## Reading the file

The file is opened with the `utf-8-sig` encoding, so a UTF-8 byte-order mark left
by Excel is consumed rather than becoming part of the first column's name. A file
that is not UTF-8, a `cp1252` export being the usual case, is reported as such
and exits `3`. csvpeek does not guess at a legacy encoding, because guessing
wrong renames columns and corrupts values without telling you.

Without `-d`, the delimiter is sniffed from the first 8192 bytes using Python's
`csv.Sniffer`, restricted to `,` `;` tab and `|`. If sniffing fails, which it
does on very short or unusual files, csvpeek falls back to a comma rather than
erroring. Pass `-d` when you know the delimiter and the file is small or odd.

The first row is always the header. Rows with fewer fields than the header are
padded with empty strings, and extra fields beyond the header are ignored. A file
with no rows at all profiles as zero rows and zero columns.

## Null values

A value is null if, after stripping surrounding whitespace and lowercasing, it is
one of:

```
""   na   n/a   null   none   nan   nil
```

This is deliberately a closed list. Sentinels that some exports use, such as
`-1`, `9999`, `?` or `-`, are *not* treated as missing, because guessing wrong
would silently distort every statistic in the column.

`null_pct` is `round(100 × nulls / (nulls + non-nulls), 1)`, so it is a
percentage of all rows, and `0.0` for a column with no rows.

## Type inference

Nulls are excluded first, then the remaining values are stripped and tested
against each type **in this order**. A column takes a type only if *every*
non-null value fits. Otherwise it falls through to the next.

| Order | Type | Accepted when every non-null value… |
| ---: | :-- | :-- |
| 1 | `empty` | there are no non-null values at all |
| 2 | `bool` | lowercases to one of `true t yes y 1` or `false f no n 0` |
| 3 | `int` | parses with Python's `int()` |
| 4 | `float` | parses with Python's `float()` |
| 5 | `date` | contains `-`, `/` or `:` **and** matches a known format |
| 6 | `string` | anything else |

Three consequences are worth knowing, because each one surprises somebody.

**A column of only `0` and `1` is `bool`, not `int`**, because `bool` is tested
first. A flag column is far more common than a genuinely two-valued integer, but
if you needed the arithmetic, this is why the numeric statistics are absent.

**A bare year stays numeric.** `date` requires a separator, so `2024` is an `int`
and not a date. That keeps ids and years out of the date bucket.

**One stray value demotes the column.** A single `N/A ` variant not in the null
list, or one `unknown` in an otherwise numeric column, makes the whole column
`string`. This is intentional. The alternative is dropping values you did not
know were being dropped.

Recognised date formats, tried in order:

```
%Y-%m-%d     %Y/%m/%d     %m/%d/%Y     %d/%m/%Y
%Y-%m-%dT%H:%M:%S          %Y-%m-%d %H:%M:%S
```

`%m/%d/%Y` is tried before `%d/%m/%Y`, so an ambiguous `03/04/2024` is read as
March 4th. csvpeek only reports *that the column is a date*. It never reformats
or re-emits the value, so the ambiguity does not propagate.

## Statistics

**Every column** gets `count` (non-null values), `nulls`, `null_pct`, and
`unique`, the number of distinct non-null values after stripping.

**`int` and `float` columns** additionally get the following:

| Field | Definition |
| :-- | :-- |
| `minimum` / `maximum` | Smallest and largest value, unrounded |
| `mean` | `statistics.fmean`, rounded to 4 decimals |
| `median` | `statistics.median`, unrounded |
| `stdev` | **Population** standard deviation (`pstdev`), rounded to 4 decimals |
| `p25` / `p75` | `statistics.quantiles(n=4)`, exclusive method, rounded to 4 decimals |

The table and Markdown output abbreviate the first two to `min` and `max` to keep
the line short. `--json` and the dataclass both use the full names.

**An `int` column reports integers.** `minimum` and `maximum` are values taken
straight from the column, so a file that says `2` is not reported as `2.0` in a
payload whose own `dtype` says `int`. `median` is one of the values too when the
count is odd, so it is an `int` there.

**An even count's median is a float**, even for an `int` column, because the two
middle values are averaged: `1` and `2` give `1.5`, and `2` and `4` give `3.0`.
Read `median` as a number rather than as an `int`.

**`mean`, `stdev`, `p25` and `p75` are always floats**, whatever the column
holds, because each of them divides. `float` columns are unaffected throughout.

One consequence is worth knowing. `minimum` and `maximum` are exact even past
`2**53`, where a float silently rounds, while `mean` and `stdev` are computed
over floats and carry that rounding.

Two more details matter if you compare csvpeek against another tool.

`stdev` is the **population** deviation, not the sample one. It divides by *n*,
not *n − 1*. A column with exactly one value reports `0.0` rather than being
undefined.

A numeric column containing a value that is not finite, `inf`, `-Infinity`,
`1e999`, or an integer too large to hold as a float, is **rejected** rather than
profiled: csvpeek reports the column and exits `3`. The standard deviation of an
infinite value is undefined, and JSON has no literal for it, so any answer here
would be either wrong or unparseable. The oversized integer is rejected too, even
though Python itself could hold it, because the mean and the deviation are
computed over floats and would overflow whatever `minimum` and `maximum` could
say. Note that `nan` is a null token, so it is counted as missing and never
reaches this check.

`p25` and `p75` use Python's default **exclusive** quantile method, which
interpolates and can therefore fall outside the range spanned by a small sample's
order statistics. They are omitted entirely for a column with fewer than two
values.

**Everything else**, meaning `string`, `bool`, `date` and `empty`, gets `top`
instead: the most common values as `(value, count)`, ordered by count descending
and then by value ascending. That secondary sort is what makes ties reproducible.
Without it the output would depend on dictionary insertion order. `-t/--top`
controls how many are kept.

## The numeric histogram

Every `int` and `float` column also gets a histogram: its values bucketed into
evenly spaced bins so the shape of the column is visible at a glance, not just its
summary statistics.

The rules:

- The bins span `minimum` to `maximum`. A column with any spread uses **ten**
  bins of equal width; a column whose values are all identical uses a **single**
  bin holding them all, because there is no range to divide.
- Bins are half-open, `[edge, next_edge)`, except the **last**, which is closed so
  the maximum value is counted in it rather than falling off the end.
- The same finite, non-null readings the statistics use feed the bins. Nulls
  never reach it, and a non-finite value is rejected before any histogram is
  built, so there is nothing here the statistics did not already accept.
- Binning is deterministic: the bin an exact value lands in is computed the same
  way every run, so two runs over one file produce the same counts.

The `table` and `md` output render the counts as a one-row sparkline after `sd`,
with each bar scaled to the fullest bin. `--json` reports the raw `edges` and
`counts` under a `histogram` key, `edges` being one longer than `counts`. See
[cli.md](cli.md#numeric-histogram) for the rendering and the JSON shape.

## The type a column almost has

A column takes a type only if *every* non-null value fits. That rule is right —
coercing away the values that do not fit is how a profiler starts lying — but on
its own it leaves the most common real question unanswered. A column reads
`string` when it was meant to be `int`, and nothing says which of ten thousand
values is responsible. Finding out means grepping, and the answer is almost
always two rows with a stray label in them.

So a `string` column also reports the type it nearly is:

```
qty  string  0  6  60 (2), 10 (1), 20 (1) · mostly int, 2 not: "twelve", "x"
```

The rules:

- Candidates are tried in the same order as inference: `bool`, `int`, `float`,
  `date`. On a tie the earlier one wins, because every int also parses as a
  float and an all-integer column should not be described as a float.
- A candidate has to fit **more than half** the non-null values. Below that
  there is no majority for the rest to be exceptions to, and a column that is
  30% numeric is text rather than a numeric column with dirt in it.
- Nulls are never outliers. `N/A` is already counted as a null, and naming it
  again as the reason the column is not an int is the same fact twice.
- At most three offending values are listed, commonest first and then
  alphabetical, with a trailing `…` when there are more. A truncated list that
  looks complete is worse than no list.
- Numeric columns never report one: they already have their type.
