# How profiling works

Every number csvpeek prints is defined here. Nothing is estimated or sampled
unless you ask for `--limit`, and nothing depends on iteration order, so two runs
over the same file produce identical output.

## Reading the file

The file is opened with the `utf-8-sig` encoding, so a UTF-8 byte-order mark left
by Excel is consumed rather than becoming part of the first column's name.

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

**`int` and `float` columns** additionally get the following, with all non-null
values read as floats:

| Field | Definition |
| :-- | :-- |
| `min` / `max` | Smallest and largest value, unrounded |
| `mean` | `statistics.fmean`, rounded to 4 decimals |
| `median` | `statistics.median`, unrounded |
| `stdev` | **Population** standard deviation (`pstdev`), rounded to 4 decimals |
| `p25` / `p75` | `statistics.quantiles(n=4)`, exclusive method, rounded to 4 decimals |

Two details matter if you compare csvpeek against another tool.

`stdev` is the **population** deviation, not the sample one. It divides by *n*,
not *n − 1*. A column with exactly one value reports `0.0` rather than being
undefined.

`p25` and `p75` use Python's default **exclusive** quantile method, which
interpolates and can therefore fall outside the range spanned by a small sample's
order statistics. They are omitted entirely for a column with fewer than two
values.

**Everything else**, meaning `string`, `bool`, `date` and `empty`, gets `top`
instead: the most common values as `(value, count)`, ordered by count descending
and then by value ascending. That secondary sort is what makes ties reproducible.
Without it the output would depend on dictionary insertion order. `-t/--top`
controls how many are kept.
