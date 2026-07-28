"""Command-line interface for csvpeek."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import Profile, profile_file

# ANSI helpers (disabled when not a TTY or --no-color)
_ACCENT = "\033[38;5;99m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _paint(enabled: bool):
    if enabled:
        return (lambda s, c: f"{c}{s}{_RESET}")
    return (lambda s, c: s)


def _fmt_num(n) -> str:
    if n is None:
        return "-"
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


def render(profile: Profile, use_color: bool) -> str:
    c = _paint(use_color)
    out: list[str] = []
    out.append(c(f"  {profile.rows} rows × {len(profile.columns)} columns", _BOLD))
    out.append("")

    name_w = max((len(col.name) for col in profile.columns), default=4)
    name_w = max(name_w, 6)

    header = f"  {'column'.ljust(name_w)}  {'type':<7} {'nulls':>7} {'unique':>7}  summary"
    out.append(c(header, _DIM))
    out.append(c("  " + "─" * (len(header) - 2), _DIM))

    for col in profile.columns:
        if col.dtype in ("int", "float"):
            summary = (
                f"min {_fmt_num(col.minimum)} · max {_fmt_num(col.maximum)} · "
                f"mean {_fmt_num(col.mean)} · median {_fmt_num(col.median)} · "
                f"sd {_fmt_num(col.stdev)}"
            )
        elif col.top:
            summary = ", ".join(f"{v} ({n})" for v, n in col.top)
        else:
            summary = c("(empty)", _DIM)

        nulls = f"{col.nulls} ({col.null_pct}%)" if col.nulls else "0"
        line = (
            f"  {c(col.name.ljust(name_w), _ACCENT)}  "
            f"{col.dtype:<7} {nulls:>7} {col.unique:>7}  {summary}"
        )
        out.append(line)

    out.append("")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="csvpeek",
        description="Profile a CSV file from the terminal — types, nulls, and stats. Zero dependencies.",
    )
    p.add_argument("file", help="path to a CSV file")
    p.add_argument("-d", "--delimiter", default=",", help="field delimiter (default: ,)")
    p.add_argument("-t", "--top", type=int, default=5, metavar="N",
                   help="show top N values for text columns (default: 5)")
    p.add_argument("-n", "--limit", type=int, default=None, metavar="ROWS",
                   help="only read the first ROWS data rows (sample large files)")
    p.add_argument("--json", action="store_true", help="emit the profile as JSON")
    p.add_argument("--no-color", action="store_true", help="disable colored output")
    p.add_argument("-V", "--version", action="version", version=f"csvpeek {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = profile_file(args.file, delimiter=args.delimiter, top_n=args.top, limit=args.limit)
    except FileNotFoundError:
        print(f"csvpeek: file not found: {args.file}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"csvpeek: could not read {args.file}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(profile.to_dict(), indent=2))
        return 0

    use_color = sys.stdout.isatty() and not args.no_color
    print(render(profile, use_color))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
