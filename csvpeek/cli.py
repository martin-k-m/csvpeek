"""Command-line interface for csvpeek."""

from __future__ import annotations

import argparse
import json
import sys
from typing import NamedTuple, Optional, TextIO

from . import __version__
from .core import DEFAULT_ENCODING, ColumnProfile, Profile, ProfileError, profile_file

# ANSI helpers (disabled when not a TTY or --no-color)
_ACCENT = "\033[38;5;99m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

# Exit codes. 1 is left alone so it keeps meaning "csvpeek itself fell over",
# which a CI gate can tell apart from a file it could not profile.
_EXIT_BAD_INPUT = 2      # missing/unreadable file, or bad arguments (argparse)
_EXIT_BAD_CONTENT = 3    # the file opened, but its contents cannot be profiled


class Glyphs(NamedTuple):
    """The non-ASCII characters the table layout leans on.

    Grouped so they can be swapped for ASCII wholesale when the output stream
    cannot encode them, rather than each one crashing at print time.
    """

    rule: str
    times: str
    dot: str
    ellipsis: str
    # Eight height levels, low to high, for the numeric histogram sparkline.
    # A single string so ``glyphs_for`` can test it for encodability alongside
    # the rest, and so it moves to ASCII as one set rather than per character.
    bars: str


UNICODE_GLYPHS = Glyphs(rule="─", times="×", dot="·", ellipsis="…", bars="▁▂▃▄▅▆▇█")
ASCII_GLYPHS = Glyphs(rule="-", times="x", dot="|", ellipsis="...", bars=".:-=+*#@")


def _stream_encoding(stream: TextIO) -> Optional[str]:
    """The codec ``stream`` encodes to, or ``None`` for an in-memory buffer."""
    enc = getattr(stream, "encoding", None)
    return enc if isinstance(enc, str) else None


def glyphs_for(stream: TextIO) -> Glyphs:
    """Pick the richest glyph set ``stream`` can actually encode.

    A cp1252 console (the Windows default without ``PYTHONUTF8``) has no box
    drawing characters, so assuming UTF-8 kills the default output entirely.
    The set moves as a whole rather than per character: cp1252 does have ``×``
    and ``·``, but emitting them there writes cp1252 bytes into output that is
    read back as UTF-8, which is how ``--format md`` produced mojibake.
    A stream with no declared encoding holds ``str`` and takes anything.
    """
    enc = _stream_encoding(stream)
    if enc is None:
        return UNICODE_GLYPHS
    try:
        "".join(UNICODE_GLYPHS).encode(enc)
    except (UnicodeEncodeError, LookupError):
        return ASCII_GLYPHS
    return UNICODE_GLYPHS


def _write(text: str, stream: TextIO) -> None:
    """Print ``text``, escaping whatever ``stream`` cannot encode.

    Glyphs are chosen up front, but column names and values come from the file
    and can be anything. Escaping keeps the character visible as ``\\uXXXX``
    instead of ending the run.
    """
    enc = _stream_encoding(stream)
    if enc is not None:
        try:
            text.encode(enc)
        except UnicodeEncodeError:
            text = text.encode(enc, "backslashreplace").decode(enc)
        except LookupError:
            pass
    try:
        print(text, file=stream)
    except BrokenPipeError:
        # `csvpeek --json | head -1` closes the pipe while there is still output
        # to write. That is the reader's decision, not an error, and docs/cli.md
        # recommends exactly this shape of pipeline. Exiting quietly beats a
        # traceback about a pipe the user deliberately closed.
        raise SystemExit(0) from None


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


def _sparkline(counts: list[int], bars: str) -> str:
    """A one-row bar of bin counts, each scaled to a height character in ``bars``.

    Heights are relative to the fullest bin, so the tallest bar is always the top
    glyph and an empty bin is always the bottom one. ``bars`` is chosen by what
    the output stream can encode, so this degrades to ASCII on a cp1252 console
    the same way the rest of the table does.
    """
    if not counts:
        return ""
    top = max(counts)
    if top == 0:
        return bars[0] * len(counts)
    last = len(bars) - 1
    return "".join(bars[round(c / top * last)] for c in counts)


# How much of one value the table and the Markdown output will print. A cell can
# legitimately hold an embedded document or a base64 blob, and printing one in
# full turns a profile meant to be read at a glance into a screenful of a single
# value. The JSON output is not clipped: that one is for a program, which wants
# the value it asked for.
_MAX_VALUE_WIDTH = 60


def _clip(value: str, glyphs: Glyphs) -> str:
    """Shorten one value for display, marking it when it was shortened."""
    if len(value) <= _MAX_VALUE_WIDTH:
        return value
    return value[:_MAX_VALUE_WIDTH] + glyphs.ellipsis


def _column_summary(col: ColumnProfile, glyphs: Glyphs = UNICODE_GLYPHS) -> str:
    """The one-line, color-free summary for a column (shared by all renderers)."""
    if col.dtype in ("int", "float"):
        sep = f" {glyphs.dot} "
        parts = [
            f"min {_fmt_num(col.minimum)}",
            f"p25 {_fmt_num(col.p25)}",
            f"median {_fmt_num(col.median)}",
            f"p75 {_fmt_num(col.p75)}",
            f"max {_fmt_num(col.maximum)}",
            f"mean {_fmt_num(col.mean)}",
            f"sd {_fmt_num(col.stdev)}",
        ]
        if col.histogram is not None:
            parts.append(f"hist {_sparkline(col.histogram.counts, glyphs.bars)}")
        return sep.join(parts)
    if col.top:
        summary = ", ".join(f"{_clip(v, glyphs)} ({n})" for v, n in col.top)
        note = _near_miss_note(col, glyphs)
        return summary + note if note else summary
    return "(empty)"


def _near_miss_note(col: ColumnProfile, glyphs: Glyphs) -> str:
    """The `mostly int, 2 not: ...` tail on a column that nearly has a type.

    Appended to the top values rather than replacing them, because both answer
    real questions and neither is a substitute for the other.

    Offending values are quoted because they are arbitrary text landing in a
    comma-separated list: a value containing a comma or a space is unreadable
    unquoted, and the whole point of this line is to be readable at a glance.
    """
    if not col.mostly:
        return ""
    missed = col.count - col.mostly_count
    shown = ", ".join(f'"{_clip(v, glyphs)}"' for v, _ in col.outliers)
    tail = f" {glyphs.dot} mostly {col.mostly}, {missed} not: {shown}"
    # The list is capped, so say when it is: a truncated list that looks
    # complete is worse than no list.
    if missed > sum(n for _, n in col.outliers):
        tail += f", {glyphs.ellipsis}"
    return tail


def _nulls_cell(col: ColumnProfile) -> str:
    return f"{col.nulls} ({col.null_pct}%)" if col.nulls else "0"


def render(profile: Profile, use_color: bool, glyphs: Glyphs = UNICODE_GLYPHS) -> str:
    c = _paint(use_color)
    out: list[str] = []
    out.append(c(f"  {profile.rows} rows {glyphs.times} {len(profile.columns)} columns", _BOLD))
    out.append("")

    name_w = max((len(col.name) for col in profile.columns), default=4)
    name_w = max(name_w, 6)

    header = f"  {'column'.ljust(name_w)}  {'type':<7} {'nulls':>7} {'unique':>7}  summary"
    out.append(c(header, _DIM))
    out.append(c("  " + glyphs.rule * (len(header) - 2), _DIM))

    for col in profile.columns:
        summary = _column_summary(col, glyphs)
        if summary == "(empty)":
            summary = c(summary, _DIM)
        line = (
            f"  {c(col.name.ljust(name_w), _ACCENT)}  "
            f"{col.dtype:<7} {_nulls_cell(col):>7} {col.unique:>7}  {summary}"
        )
        out.append(line)

    out.append("")
    return "\n".join(out)


def _md_escape(text: str) -> str:
    """Escape characters that would break a Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def render_markdown(profile: Profile, glyphs: Glyphs = UNICODE_GLYPHS) -> str:
    """Render the profile as a Markdown document, a table you can paste into a PR."""
    out: list[str] = [
        "# CSV profile",
        "",
        f"**{profile.rows} rows {glyphs.times} {len(profile.columns)} columns**",
        "",
        "| Column | Type | Nulls | Unique | Summary |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for col in profile.columns:
        out.append(
            f"| `{_md_escape(col.name)}` | {col.dtype} | {_nulls_cell(col)} | "
            f"{col.unique} | {_md_escape(_column_summary(col, glyphs))} |"
        )
    out.append("")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="csvpeek",
        description="Profile a CSV file from the terminal: types, nulls, and stats. "
                    "Zero dependencies.",
    )
    p.add_argument("file", help="path to a CSV file, or - to read from standard input")
    p.add_argument("-d", "--delimiter", default=None,
                   help="field delimiter (default: auto-detect , ; tab |)")
    p.add_argument("-t", "--top", type=int, default=5, metavar="N",
                   help="show top N values for text columns (default: 5)")
    p.add_argument("-n", "--limit", type=int, default=None, metavar="ROWS",
                   help="only read the first ROWS data rows (sample large files)")
    p.add_argument("-c", "--columns", default=None, metavar="A,B,C",
                   help="profile only these columns, comma-separated, in the order given")
    p.add_argument("--format", choices=["table", "md", "json"], default="table",
                   help="output format: table (default), md (Markdown), or json")
    p.add_argument("--json", action="store_true", help="shortcut for --format json")
    p.add_argument("--encoding", default=DEFAULT_ENCODING, metavar="ENC",
                   help="input text encoding (default: %(default)s, which is UTF-8 with "
                        "an Excel byte order mark tolerated); try cp1252 or latin-1")
    p.add_argument("--no-color", action="store_true", help="disable colored output")
    p.add_argument("-V", "--version", action="version", version=f"csvpeek {__version__}")
    return p


def _fail(message: str, code: int) -> int:
    _write(f"csvpeek: {message}", sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    select = None
    if args.columns is not None:
        select = [name.strip() for name in args.columns.split(",") if name.strip()]
        if not select:
            return _fail("--columns needs at least one column name", _EXIT_BAD_INPUT)

    try:
        profile = profile_file(
            args.file, delimiter=args.delimiter, top_n=args.top, limit=args.limit,
            select=select, encoding=args.encoding,
        )
    except FileNotFoundError:
        return _fail(f"file not found: {args.file}", _EXIT_BAD_INPUT)
    except OSError as exc:
        return _fail(f"could not read {args.file}: {exc}", _EXIT_BAD_INPUT)
    except ProfileError as exc:
        return _fail(str(exc), _EXIT_BAD_CONTENT)

    glyphs = glyphs_for(sys.stdout)
    fmt = "json" if args.json else args.format
    if fmt == "json":
        # json.dumps escapes non-ASCII by default, so this needs no glyph care.
        _write(json.dumps(profile.to_dict(histograms=True), indent=2), sys.stdout)
    elif fmt == "md":
        _write(render_markdown(profile, glyphs), sys.stdout)
    else:
        use_color = sys.stdout.isatty() and not args.no_color
        _write(render(profile, use_color, glyphs), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
