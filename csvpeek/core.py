"""Core profiling logic — pure standard library, deterministic, no side effects.

The type inference and statistics here are intentionally simple and explainable:
the same input always produces the same profile, and every number is something you
could compute by hand from the column.
"""

from __future__ import annotations

import csv
import statistics
from datetime import datetime
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

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
    # numeric-only (None for non-numeric columns)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
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
        return {
            "rows": self.rows,
            "columns": [
                {
                    "name": c.name,
                    "dtype": c.dtype,
                    "count": c.count,
                    "nulls": c.nulls,
                    "null_pct": c.null_pct,
                    "unique": c.unique,
                    "min": c.minimum,
                    "max": c.maximum,
                    "mean": c.mean,
                    "median": c.median,
                    "stdev": c.stdev,
                    "top": [{"value": v, "count": n} for v, n in c.top],
                }
                for c in self.columns
            ],
        }


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
        nums = [float(v) for v in present]
        col.minimum = min(nums)
        col.maximum = max(nums)
        col.mean = round(statistics.fmean(nums), 4)
        col.median = statistics.median(nums)
        col.stdev = round(statistics.pstdev(nums), 4) if len(nums) > 1 else 0.0
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

    ``limit`` caps how many data rows are read — useful for sampling a large
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


def profile_file(
    path: str, delimiter: str = ",", top_n: int = 5, limit: Optional[int] = None
) -> Profile:
    """Read a CSV file from ``path`` and profile it (optionally sampling ``limit`` rows)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return Profile(rows=0, columns=[])
        return profile_rows(header, reader, top_n=top_n, limit=limit)
