"""Core profiling logic: pure standard library, deterministic, no side effects.

The type inference and statistics here are intentionally simple and explainable:
the same input always produces the same profile, and every number is something you
could compute by hand from the column.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
import sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence, TextIO, Union

# Version of the JSON payload produced by ``Profile.to_dict``. Bumped whenever a
# key is renamed, removed, or changes meaning, so a consumer can detect the
# change up front instead of discovering it one missing field at a time.
SCHEMA_VERSION = 1

# How many bins the numeric histogram uses when a column spans a range. A column
# whose values are all identical collapses to a single bin instead. Kept small
# and fixed so the sparkline stays one glanceable row and two runs match.
HIST_BINS = 10

# A statistic is an int only where an int column can produce one exactly; see
# ``_profile_column``.
Number = Union[int, float]

# Values treated as "missing" regardless of column type (case-insensitive).
NULL_TOKENS = frozenset({"", "na", "n/a", "null", "none", "nan", "nil"})
_TRUE = frozenset({"true", "t", "yes", "y", "1"})
_FALSE = frozenset({"false", "f", "no", "n", "0"})

# Common date/time formats, tried in order. Kept small and unambiguous.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


class ProfileError(Exception):
    """The input is readable but cannot be profiled as it stands.

    Separate from ``OSError``: the file was opened fine, its *contents* are the
    problem, which is a different thing for a caller to react to.
    """


def is_null(value: str) -> bool:
    return value.strip().lower() in NULL_TOKENS


def _try_int(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def _try_float(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _try_date(value: str) -> bool:
    # Require a separator so bare numbers (years, ids) aren't read as dates.
    if not any(sep in value for sep in "-/:"):
        return False
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def infer_type(values: Sequence[str]) -> str:
    """Infer a column type from its non-null values.

    Returns one of: ``empty``, ``bool``, ``int``, ``float``, ``date``, ``string``.
    A column takes a specific type only if *every* non-null value fits it; one
    stray label demotes the whole column to ``string`` (no silent coercion).
    """
    non_null = [v.strip() for v in values if not is_null(v)]
    if not non_null:
        return "empty"

    lowered = [v.lower() for v in non_null]
    if all(v in _TRUE or v in _FALSE for v in lowered):
        return "bool"
    if all(_try_int(v) for v in non_null):
        return "int"
    if all(_try_float(v) for v in non_null):
        return "float"
    if all(_try_date(v) for v in non_null):
        return "date"
    return "string"


# The candidate types a column can nearly be, in the order infer_type tries
# them. Order matters on a tie: every int also parses as a float, so the two
# candidates score equally on a clean integer column and the more specific one
# has to win.
_CANDIDATES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("bool", lambda v: v.lower() in _TRUE or v.lower() in _FALSE),
    ("int", _try_int),
    ("float", _try_float),
    ("date", _try_date),
)

# How much of a column has to fit a type before the misfits are worth naming.
# Below half there is no majority to be the exception to, and a column that is
# 30% numeric is a text column rather than a numeric one with dirt in it.
_NEAR_MISS_FLOOR = 0.5


def near_miss(present: Sequence[str], limit: int = 3) -> tuple[str | None, int, list[tuple[str, int]]]:
    """The type a string column *almost* is, and the values stopping it.

    A column takes a type only if every value fits, which is the right rule —
    silently coercing away the values that do not fit is how a profiler starts
    lying. But it leaves the most common real question unanswered: a column
    reads `string` when it was supposed to be `int`, and the profile does not
    say which of ten thousand values is responsible. Finding that out means
    grepping, and the answer is usually two rows with `N/A ` or a stray label.

    Returns the best-fitting candidate type, how many values fit it, and the
    most common values that do not, or (None, 0, []) when the column is not
    close to any type.
    """
    if not present:
        return None, 0, []

    best_type: str | None = None
    best_fit = 0
    for name, fits in _CANDIDATES:
        n = sum(1 for v in present if fits(v))
        # Strictly greater, so an earlier and more specific candidate keeps a
        # tie: an all-integer column is int, not float.
        if n > best_fit:
            best_type, best_fit = name, n

    if best_type is None or best_fit == len(present):
        # Either nothing fits anything, or everything fits — and if everything
        # fits, infer_type already gave the column that type and there is no
        # near miss to report.
        return None, 0, []
    if best_fit < len(present) * _NEAR_MISS_FLOOR:
        return None, 0, []

    fits = dict(_CANDIDATES)[best_type]
    counts: dict[str, int] = {}
    for v in present:
        if not fits(v):
            counts[v] = counts.get(v, 0) + 1
    # Same ordering rule as `top`: commonest first, then alphabetical, so two
    # runs over one file print the same thing.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return best_type, best_fit, ordered[:limit]


@dataclass
class Histogram:
    """The shape of a numeric column, as bin counts over evenly spaced bins.

    ``edges`` has one more entry than ``counts``: ``edges[i]`` and ``edges[i+1]``
    bound bin ``i``. Bins are half-open ``[edges[i], edges[i+1])`` except the last,
    which is closed so the maximum value lands inside it rather than falling off
    the end. A column whose values are all equal has a single bin.
    """

    edges: list[float]
    counts: list[int]


def _histogram(nums: Sequence[float]) -> Histogram:
    """Bucket already-parsed, finite numbers into ``HIST_BINS`` even bins.

    The caller passes the same float readings the statistics use, so the non-null
    handling and the non-finite guard in ``_profile_column`` already apply: nulls
    never reach here, and an infinity would have been rejected before this runs.
    The bin an exact value lands in is computed the same way every time, so the
    counts are deterministic.
    """
    lo = min(nums)
    hi = max(nums)
    if hi == lo:
        # No spread to divide, so one bin holds everything. Reporting ten bins
        # with nine empty would imply a range that is not there.
        return Histogram(edges=[lo, hi], counts=[len(nums)])

    width = (hi - lo) / HIST_BINS
    counts = [0] * HIST_BINS
    for v in nums:
        idx = int((v - lo) / width)
        # The maximum value divides out to exactly HIST_BINS; clamp it into the
        # last bin so the closed top edge holds it. Guard the low side too against
        # a float rounding a hair below lo.
        if idx >= HIST_BINS:
            idx = HIST_BINS - 1
        elif idx < 0:
            idx = 0
        counts[idx] += 1
    edges = [lo + i * width for i in range(HIST_BINS + 1)]
    edges[-1] = hi  # exact, rather than lo + HIST_BINS*width and its rounding
    return Histogram(edges=edges, counts=counts)


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    count: int          # non-null values
    nulls: int
    unique: int
    # numeric-only (None for non-numeric columns). An int column reports the
    # statistics it can answer exactly as ints, so minimum, maximum and median
    # are ints there; mean, stdev and the quartiles divide and stay floats.
    minimum: Number | None = None
    maximum: Number | None = None
    mean: float | None = None
    median: Number | None = None
    stdev: float | None = None
    p25: float | None = None
    p75: float | None = None
    # string/bool: most common values as (value, count), descending then by value
    top: list[tuple[str, int]] = field(default_factory=list)
    # string only: the type this column almost is, and what is stopping it.
    mostly: str | None = None
    mostly_count: int = 0
    outliers: list[tuple[str, int]] = field(default_factory=list)
    # numeric-only: the column's distribution as evenly spaced bin counts.
    histogram: Histogram | None = None

    @property
    def null_pct(self) -> float:
        total = self.count + self.nulls
        return 0.0 if total == 0 else round(100 * self.nulls / total, 1)


@dataclass
class Profile:
    rows: int
    columns: list[ColumnProfile]

    def to_dict(self, histograms: bool = False) -> dict:
        """The JSON-ready form: a schema version, then the profile itself.

        Every column key is named after the attribute it comes from. ``top`` is
        the one field that changes shape, from pairs to objects, because JSON
        has no tuple.

        ``histograms`` opts into an extra ``"histogram"`` key on each column: an
        object with ``edges`` and ``counts`` for a numeric column, ``null`` for
        the rest. It is off by default so the payload above stays exactly what it
        was, which is why ``schema`` does not move: the key is additive and
        optional, and a consumer that does not recognise it can ignore it. The
        CLI turns it on for ``--json``.
        """
        out = {
            "schema": SCHEMA_VERSION,
            "rows": self.rows,
            "columns": [
                {
                    "name": c.name,
                    "dtype": c.dtype,
                    "count": c.count,
                    "nulls": c.nulls,
                    "null_pct": c.null_pct,
                    "unique": c.unique,
                    "minimum": c.minimum,
                    "maximum": c.maximum,
                    "mean": c.mean,
                    "median": c.median,
                    "stdev": c.stdev,
                    "p25": c.p25,
                    "p75": c.p75,
                    "top": [{"value": v, "count": n} for v, n in c.top],
                    "mostly": c.mostly,
                    "mostly_count": c.mostly_count,
                    "outliers": [{"value": v, "count": n} for v, n in c.outliers],
                }
                for c in self.columns
            ],
        }
        if histograms:
            for cell, c in zip(out["columns"], self.columns):
                cell["histogram"] = (
                    None
                    if c.histogram is None
                    else {
                        "edges": [round(e, 4) for e in c.histogram.edges],
                        "counts": c.histogram.counts,
                    }
                )
        return out


def _reject_non_finite(name: str, present: Sequence[str], nums: Sequence[float]) -> None:
    """Refuse a numeric column holding an infinity.

    ``inf``, ``-infinity`` and integers too large for a float all parse happily
    and then break ``statistics`` a few lines later. There is also no honest
    answer to report: the standard deviation of an infinite value is undefined,
    and JSON has no literal for it, so ``--json`` would emit something no strict
    parser accepts. Saying so is better than either.
    """
    for raw, num in zip(present, nums):
        if not math.isfinite(num):
            shown = raw if len(raw) <= 32 else raw[:32] + "..."
            raise ProfileError(
                f"column {name!r} contains a value that is not a finite number: {shown}"
            )


def _finite(name: str, stat: str, value: Number) -> Number:
    """Refuse a computed statistic that is not finite.

    ``_reject_non_finite`` checks what was parsed out of the file. This checks
    what came back out of ``statistics``, which is a different problem: a column
    of ``1e308`` and ``-1e308`` is entirely finite on the way in and still
    produces an infinite spread and infinite quartiles. Emitting those would put
    a bare ``Infinity`` in ``--json``, which no strict parser accepts, so the
    documented ``--json | jq`` pipeline would break at exit 0.
    """
    if not math.isfinite(value):
        raise ProfileError(
            f"column {name!r} has a {stat} that is not a finite number; "
            "the values are too spread out to summarise"
        )
    return value


def _profile_column(name: str, values: Sequence[str], top_n: int) -> ColumnProfile:
    nulls = sum(1 for v in values if is_null(v))
    present = [v.strip() for v in values if not is_null(v)]
    dtype = infer_type(values)
    unique = len(set(present))

    col = ColumnProfile(
        name=name,
        dtype=dtype,
        count=len(present),
        nulls=nulls,
        unique=unique,
    )

    if dtype in ("int", "float") and present:
        # Two readings of the same values. The float one is what the guards and
        # the dividing statistics need; the exact one keeps an int column's
        # min/max/median as ints, so a file saying 2 is not reported as 2.0 in a
        # payload whose own dtype says int. Parsing the strings as floats first
        # also keeps the non-finite guard intact: float("1" * 400) is inf and is
        # rejected below, where int() would happily build the number and only
        # blow up later inside fmean.
        nums = [float(v) for v in present]
        _reject_non_finite(name, present, nums)
        exact: Sequence[Number] = [int(v) for v in present] if dtype == "int" else nums
        try:
            col.minimum = min(exact)
            col.maximum = max(exact)
            col.mean = _finite(name, "mean", statistics.fmean(nums))
            # Odd counts return a value straight from the column, so an int
            # column keeps its int. Even counts average the middle pair, which
            # divides, so those come back as floats.
            col.median = _finite(name, "median", statistics.median(exact))
            col.stdev = (
                _finite(name, "stdev", statistics.pstdev(nums)) if len(nums) > 1 else 0.0
            )
            if len(nums) >= 2:
                q1, _, q3 = statistics.quantiles(nums, n=4)  # exclusive method (default)
                col.p25 = _finite(name, "p25", q1)
                col.p75 = _finite(name, "p75", q3)
        except OverflowError as exc:
            # fsum raises this rather than returning inf. Values near the top of
            # the float range are individually finite, so the input guard above
            # passes them and the sum is what overflows.
            raise ProfileError(
                f"column {name!r} has values too large to summarise: {exc}"
            ) from exc
        # Same finite float readings the statistics used, so the guard above has
        # already rejected any infinity before it reaches the bins.
        col.histogram = _histogram(nums)
        col.mean = None if col.mean is None else round(col.mean, 4)
        col.stdev = None if col.stdev is None else round(col.stdev, 4)
        col.p25 = None if col.p25 is None else round(col.p25, 4)
        col.p75 = None if col.p75 is None else round(col.p75, 4)
    elif present:
        counts: dict[str, int] = {}
        for v in present:
            counts[v] = counts.get(v, 0) + 1
        # deterministic ordering: by count desc, then value asc
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        col.top = ordered[:top_n]
        if dtype == "string":
            col.mostly, col.mostly_count, col.outliers = near_miss(present)

    return col


def _select_indices(header: Sequence[str], select: Sequence[str]) -> list[int]:
    """The file-order positions of the named columns, in the order named.

    Raises ``ProfileError`` naming every column that is not in the header, before
    a single data row is read, so a typo fails fast and says what is available
    rather than profiling nothing. A name repeated in the header resolves to its
    first occurrence.
    """
    pos: dict[str, int] = {}
    for i, name in enumerate(header):
        pos.setdefault(name, i)
    unknown = [name for name in select if name not in pos]
    if unknown:
        missing = ", ".join(repr(u) for u in unknown)
        available = ", ".join(repr(h) for h in header) or "(none)"
        raise ProfileError(
            f"no such column: {missing}; available columns are {available}"
        )
    return [pos[name] for name in select]


def profile_rows(
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
    top_n: int = 5,
    limit: Optional[int] = None,
    select: Optional[Sequence[str]] = None,
) -> Profile:
    """Profile already-parsed rows against a header.

    ``limit`` caps how many data rows are read, useful for sampling a large
    file. ``None`` reads everything. ``select`` restricts profiling to the named
    columns, in the order named; ``None`` profiles every column. An unknown name
    raises ``ProfileError`` before any row is read.
    """
    chosen = list(range(len(header))) if select is None else _select_indices(header, select)

    columns: list[list[str]] = [[] for _ in chosen]
    n_rows = 0
    for row in rows:
        if limit is not None and n_rows >= limit:
            break
        n_rows += 1
        for j, ci in enumerate(chosen):
            columns[j].append(row[ci] if ci < len(row) else "")

    profiles = [
        _profile_column(header[ci], columns[j], top_n) for j, ci in enumerate(chosen)
    ]
    return Profile(rows=n_rows, columns=profiles)


def sniff_delimiter(sample: str) -> str:
    """Guess a delimiter from a text sample; fall back to comma."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _profile_stream(
    fh: TextIO,
    delimiter: Optional[str],
    top_n: int,
    limit: Optional[int],
    select: Optional[Sequence[str]] = None,
) -> Profile:
    """Profile an open text stream. Shared by the file and stdin readers.

    The stream must be seekable, because sniffing a delimiter reads a sample and
    then rewinds. A real file is; the in-memory buffer stdin is read into is too.
    """
    if delimiter is None:
        delimiter = sniff_delimiter(fh.read(8192))
        fh.seek(0)
    try:
        reader = csv.reader(fh, delimiter=delimiter)
    except TypeError as exc:
        # csv rejects a delimiter that is not exactly one character with a
        # TypeError, not a csv.Error, so the caller's handler misses it. -d ";;"
        # is a user typo and should read as one, not as a crash.
        raise ProfileError(
            f"delimiter must be a single character, got {delimiter!r}"
        ) from exc
    try:
        header = next(reader)
    except StopIteration:
        return Profile(rows=0, columns=[])
    return profile_rows(header, reader, top_n=top_n, limit=limit, select=select)


def profile_file(
    path: str,
    delimiter: Optional[str] = None,
    top_n: int = 5,
    limit: Optional[int] = None,
    select: Optional[Sequence[str]] = None,
) -> Profile:
    """Read a CSV file from ``path`` and profile it.

    ``path`` may be ``"-"`` to read the CSV from standard input, so csvpeek fits
    into a pipe (``cat data.csv | csvpeek -``). ``delimiter`` defaults to
    auto-detection (comma/semicolon/tab/pipe). ``limit`` optionally samples only
    the first N data rows.

    Raises ``ProfileError`` when the bytes are not UTF-8, or when the CSV module
    refuses the input (an unterminated quote, or a field past its size limit).
    """
    if path == "-":
        # stdin is not seekable, so read it whole and profile the buffer. The
        # decode consumes a UTF-8 BOM the same way ``utf-8-sig`` does for a file.
        raw = sys.stdin.buffer.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            bad = exc.object[exc.start]
            raise ProfileError(
                f"standard input is not UTF-8 text (byte 0x{bad:02x} is not valid "
                "there); convert it to UTF-8 first"
            ) from exc
        try:
            return _profile_stream(io.StringIO(text, newline=""), delimiter, top_n, limit, select)
        except csv.Error as exc:
            raise ProfileError(f"standard input could not be parsed as CSV: {exc}") from exc

    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return _profile_stream(fh, delimiter, top_n, limit, select)
    except UnicodeDecodeError as exc:
        bad = exc.object[exc.start]
        raise ProfileError(
            f"{path} is not UTF-8 text (byte 0x{bad:02x} is not valid there); "
            "convert it to UTF-8 first"
        ) from exc
    except csv.Error as exc:
        # The reader is consumed inside the ``with``, so its errors surface here.
        raise ProfileError(f"{path} could not be parsed as CSV: {exc}") from exc
