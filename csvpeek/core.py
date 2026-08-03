"""Core profiling logic: pure standard library, deterministic, no side effects.

The type inference and statistics here are intentionally simple and explainable:
the same input always produces the same profile, and every number is something you
could compute by hand from the column.
"""

from __future__ import annotations

import csv
import math
import statistics
from datetime import datetime
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence, Union

# Version of the JSON payload produced by ``Profile.to_dict``. Bumped whenever a
# key is renamed, removed, or changes meaning, so a consumer can detect the
# change up front instead of discovering it one missing field at a time.
SCHEMA_VERSION = 1

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

    @property
    def null_pct(self) -> float:
        total = self.count + self.nulls
        return 0.0 if total == 0 else round(100 * self.nulls / total, 1)


@dataclass
class Profile:
    rows: int
    columns: list[ColumnProfile]

    def to_dict(self) -> dict:
        """The JSON-ready form: a schema version, then the profile itself.

        Every column key is named after the attribute it comes from. ``top`` is
        the one field that changes shape, from pairs to objects, because JSON
        has no tuple.
        """
        return {
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
                }
                for c in self.columns
            ],
        }


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

    return col


def profile_rows(
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
    top_n: int = 5,
    limit: Optional[int] = None,
) -> Profile:
    """Profile already-parsed rows against a header.

    ``limit`` caps how many data rows are read, useful for sampling a large
    file. ``None`` reads everything.
    """
    columns: list[list[str]] = [[] for _ in header]
    n_rows = 0
    for row in rows:
        if limit is not None and n_rows >= limit:
            break
        n_rows += 1
        for i in range(len(header)):
            columns[i].append(row[i] if i < len(row) else "")

    profiles = [
        _profile_column(name, columns[i], top_n) for i, name in enumerate(header)
    ]
    return Profile(rows=n_rows, columns=profiles)


def sniff_delimiter(sample: str) -> str:
    """Guess a delimiter from a text sample; fall back to comma."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def profile_file(
    path: str, delimiter: Optional[str] = None, top_n: int = 5, limit: Optional[int] = None
) -> Profile:
    """Read a CSV file from ``path`` and profile it.

    ``delimiter`` defaults to auto-detection (comma/semicolon/tab/pipe).
    ``limit`` optionally samples only the first N data rows.

    Raises ``ProfileError`` when the bytes are not UTF-8, or when the CSV module
    refuses the file (an unterminated quote, or a field past its size limit).
    """
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            if delimiter is None:
                delimiter = sniff_delimiter(fh.read(8192))
                fh.seek(0)
            try:
                reader = csv.reader(fh, delimiter=delimiter)
            except TypeError as exc:
                # csv rejects a delimiter that is not exactly one character with
                # a TypeError, not a csv.Error, so the handler below misses it.
                # -d ";;" is a user typo and should read as one, not as a crash.
                raise ProfileError(
                    f"delimiter must be a single character, got {delimiter!r}"
                ) from exc
            try:
                header = next(reader)
            except StopIteration:
                return Profile(rows=0, columns=[])
            return profile_rows(header, reader, top_n=top_n, limit=limit)
    except UnicodeDecodeError as exc:
        bad = exc.object[exc.start]
        raise ProfileError(
            f"{path} is not UTF-8 text (byte 0x{bad:02x} is not valid there); "
            "convert it to UTF-8 first"
        ) from exc
    except csv.Error as exc:
        # The reader is consumed inside the ``with``, so its errors surface here.
        raise ProfileError(f"{path} could not be parsed as CSV: {exc}") from exc
