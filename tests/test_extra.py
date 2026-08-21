"""Extra coverage: input parsing edge cases, type inference corners, the near
miss on every candidate type, and reading a CSV from standard input.

Kept separate from the owner's suites so the additions are easy to see.
"""

import csv
import io
import json
import sys
import types

import pytest

from csvpeek.cli import main
from csvpeek.core import (
    MAX_FIELD_SIZE,
    ProfileError,
    infer_type,
    near_miss,
    profile_file,
    profile_rows,
    sniff_delimiter,
)

# --- input parsing ----------------------------------------------------------


def test_quoted_field_with_comma_stays_one_value(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text('name,note\n"Doe, Jane","a, b, c"\n', encoding="utf-8")
    prof = profile_file(str(p))
    assert [c.name for c in prof.columns] == ["name", "note"]
    assert prof.rows == 1
    assert prof.columns[0].top == [("Doe, Jane", 1)]


def test_quoted_field_with_embedded_newline_is_one_row(tmp_path):
    p = tmp_path / "q.csv"
    # write bytes so the platform does not rewrite the embedded newline.
    p.write_bytes(b'name,bio\nann,"line one\nline two"\n')
    prof = profile_file(str(p))
    assert prof.rows == 1
    assert prof.columns[1].top == [("line one\nline two", 1)]


def test_utf8_bom_is_stripped_from_the_first_header(tmp_path):
    p = tmp_path / "bom.csv"
    # Excel writes a UTF-8 BOM; it must not become part of the first column name.
    p.write_bytes(b"\xef\xbb\xbfname,age\nann,9\n")
    prof = profile_file(str(p))
    assert [c.name for c in prof.columns] == ["name", "age"]


def test_header_only_file_has_columns_but_no_rows(tmp_path):
    p = tmp_path / "head.csv"
    p.write_text("a,b,c\n", encoding="utf-8")
    prof = profile_file(str(p))
    assert prof.rows == 0
    assert [c.name for c in prof.columns] == ["a", "b", "c"]
    # No values reached any column, so each infers as empty.
    assert all(c.dtype == "empty" and c.count == 0 for c in prof.columns)


def test_extra_fields_beyond_the_header_are_ignored():
    prof = profile_rows(["a", "b"], [["1", "2", "3", "4"]])
    assert len(prof.columns) == 2
    assert prof.columns[0].top == [("1", 1)]


def test_explicit_delimiter_overrides_autodetection(tmp_path):
    p = tmp_path / "pipe.csv"
    p.write_text("a|b\n1|2\n3|4\n", encoding="utf-8")
    prof = profile_file(str(p), delimiter="|")
    assert [c.name for c in prof.columns] == ["a", "b"]
    assert prof.rows == 2


def test_sniff_pipe_and_comma_fallback():
    assert sniff_delimiter("a|b|c\n1|2|3\n4|5|6") == "|"
    # A one-word sample gives the sniffer nothing to go on; it falls back.
    assert sniff_delimiter("word") == ","


# --- type inference corners -------------------------------------------------


def test_mixed_int_and_float_promotes_to_float():
    col = profile_rows(["x"], [["1"], ["2"], ["3.5"]]).columns[0]
    assert col.dtype == "float"
    assert isinstance(col.minimum, float) and col.minimum == 1.0
    assert col.maximum == 3.5


def test_negative_and_signed_numbers_are_numeric():
    assert infer_type(["-5", "+3", "0"]) == "int"
    assert infer_type(["-5", "3.5"]) == "float"


def test_a_bool_column_reports_top_not_stats():
    col = profile_rows(["flag"], [["0"], ["1"], ["1"]]).columns[0]
    assert col.dtype == "bool"
    assert col.minimum is None and col.mean is None
    assert col.top == [("1", 2), ("0", 1)]


def test_a_date_column_reports_top_values():
    col = profile_rows(["d"], [["2024-01-01"], ["2024-01-02"], ["2024-01-01"]]).columns[0]
    assert col.dtype == "date"
    assert col.top[0] == ("2024-01-01", 2)
    assert col.minimum is None  # dates are not summarised numerically


def test_a_column_of_only_nulls_is_empty():
    col = profile_rows(["x"], [[""], ["NA"], ["n/a"]]).columns[0]
    assert col.dtype == "empty"
    assert col.count == 0 and col.nulls == 3
    assert col.top == []


def test_whitespace_only_values_count_as_null():
    # "1" alone would infer as bool (it is a true token), so use a plain number.
    col = profile_rows(["x"], [["   "], ["5"], ["7"]]).columns[0]
    assert col.nulls == 1
    assert col.dtype == "int"


def test_null_pct_rounds_to_one_decimal():
    # 1 of 3 null -> 33.3, not 33.33
    col = profile_rows(["x"], [["1"], ["2"], [""]]).columns[0]
    assert col.null_pct == 33.3


# --- the near miss on each candidate type -----------------------------------


def test_near_miss_names_a_bool_column():
    kind, fit, outliers = near_miss(["true", "false", "yes", "maybe"])
    assert (kind, fit) == ("bool", 3)
    assert outliers == [("maybe", 1)]


def test_near_miss_names_a_float_column():
    kind, fit, _ = near_miss(["1.5", "2.5", "3.5", "x"])
    assert (kind, fit) == ("float", 3)


def test_near_miss_names_a_date_column():
    kind, fit, outliers = near_miss(["2024-01-01", "2024-01-02", "2024-01-03", "nope"])
    assert (kind, fit) == ("date", 3)
    assert outliers == [("nope", 1)]


def test_near_miss_at_exactly_half_is_reported():
    # Documents current behaviour: at exactly half the majority test passes, so a
    # 2-of-4 column still names its near miss. See profiling.md for the rule.
    assert near_miss(["1", "2", "a", "b"]) == ("int", 2, [("a", 1), ("b", 1)])


def test_near_miss_below_half_is_not_reported():
    assert near_miss(["1", "a", "b", "c", "d"]) == (None, 0, [])


# --- CLI flags not otherwise covered ----------------------------------------


def test_cli_top_limits_shown_values(capsys, tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("c\nred\nred\nblue\ngreen\nteal\n", encoding="utf-8")
    assert main([str(p), "--no-color", "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "red (2)" in out
    assert "green" not in out  # capped at one value


def test_cli_limit_samples_rows(capsys, tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("x\n1\n2\n3\n4\n5\n", encoding="utf-8")
    assert main([str(p), "--json", "--limit", "2"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 2


def test_cli_explicit_delimiter(capsys, tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("a;b\n1;2\n", encoding="utf-8")
    assert main([str(p), "--json", "-d", ";"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in payload["columns"]] == ["a", "b"]


def test_cli_version_prints_and_exits_zero(capsys):
    from csvpeek import __version__

    with pytest.raises(SystemExit) as exc:
        main(["-V"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_table_output_shows_empty_marker_for_an_all_null_column(capsys, tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("x,y\n,1\n,2\n", encoding="utf-8")
    assert main([str(p), "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "(empty)" in out


# --- reading from standard input --------------------------------------------


def _feed_stdin(monkeypatch, data: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(data)))


def test_stdin_is_profiled_like_a_file(monkeypatch, capsys):
    _feed_stdin(monkeypatch, b"name,age\nann,9\nbob,7\n")
    assert main(["-", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 2
    assert [c["name"] for c in payload["columns"]] == ["name", "age"]
    assert payload["columns"][1]["dtype"] == "int"


def test_stdin_autodetects_delimiter(monkeypatch, capsys):
    _feed_stdin(monkeypatch, b"a;b\n1;2\n3;4\n")
    assert main(["-", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in payload["columns"]] == ["a", "b"]


def test_stdin_strips_a_utf8_bom(monkeypatch):
    _feed_stdin(monkeypatch, b"\xef\xbb\xbfname,age\nann,9\n")
    prof = profile_file("-")
    assert [c.name for c in prof.columns] == ["name", "age"]


def test_stdin_empty_input_is_zero_by_zero(monkeypatch):
    _feed_stdin(monkeypatch, b"")
    prof = profile_file("-")
    assert prof.rows == 0 and prof.columns == []


def test_stdin_non_utf8_raises_profile_error(monkeypatch):
    _feed_stdin(monkeypatch, "name\nJosé\n".encode("cp1252"))
    with pytest.raises(ProfileError, match="standard input is not UTF-8 text"):
        profile_file("-")


def test_stdin_bad_csv_raises_profile_error(monkeypatch, squeezed_field_limit):
    _feed_stdin(monkeypatch, b"a,b\n" + b"x" * (squeezed_field_limit + 1) + b",1\n")
    with pytest.raises(ProfileError, match="standard input could not be parsed as CSV"):
        profile_file("-")


def test_stdin_exits_zero_end_to_end(monkeypatch, capsys):
    _feed_stdin(monkeypatch, b"x\n1\n2\n3\n")
    assert main(["-", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "3 rows" in out


# --- encodings that are not UTF-8, and cells larger than the stdlib default ---


def test_a_non_utf8_file_names_the_flag_that_reads_it(tmp_path):
    p = tmp_path / "latin.csv"
    p.write_bytes("name,city\nJos\xe9,M\xe1laga\n".encode("cp1252"))
    with pytest.raises(ProfileError, match="--encoding cp1252"):
        profile_file(str(p))


def test_the_encoding_argument_reads_a_cp1252_file(tmp_path):
    p = tmp_path / "latin.csv"
    p.write_bytes("name,city\nJos\xe9,M\xe1laga\n".encode("cp1252"))
    profile = profile_file(str(p), encoding="cp1252")
    assert profile.rows == 1
    assert [c.name for c in profile.columns] == ["name", "city"]
    assert profile.columns[0].top == [("Jos\xe9", 1)]


def test_the_encoding_argument_reaches_the_cli(tmp_path, capsys):
    p = tmp_path / "latin.csv"
    p.write_bytes("name,city\nJos\xe9,M\xe1laga\n".encode("cp1252"))
    assert main([str(p), "--encoding", "cp1252", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 1


def test_an_unknown_encoding_is_reported_not_raised_raw(tmp_path, capsys):
    p = tmp_path / "a.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="unknown encoding"):
        profile_file(str(p), encoding="no-such-codec")
    assert main([str(p), "--encoding", "no-such-codec"]) == 3
    assert "unknown encoding" in capsys.readouterr().err


def test_stdin_honours_the_encoding_argument(monkeypatch):
    _feed_stdin(monkeypatch, "name\nJos\xe9\n".encode("cp1252"))
    profile = profile_file("-", encoding="cp1252")
    assert profile.columns[0].top == [("Jos\xe9", 1)]


def test_a_cell_past_the_stdlib_default_is_profiled_not_refused(tmp_path):
    p = tmp_path / "big.csv"
    blob = "x" * 200_000
    # Path.write_text gained newline= in 3.10; the support floor is 3.9.
    with open(p, "w", newline="", encoding="utf-8") as fh:
        fh.write("a,b\n" + blob + ",1\n")
    profile = profile_file(str(p))
    assert profile.rows == 1
    assert profile.columns[0].top == [(blob, 1)]


def test_the_raised_field_limit_is_still_a_limit():
    # A limit that admits everything is not a limit.
    assert csv.field_size_limit() == MAX_FIELD_SIZE
    assert MAX_FIELD_SIZE < 2 ** 31 - 1


def test_a_very_long_value_is_clipped_in_the_table_not_in_the_json(tmp_path, capsys):
    blob = "x" * 5000
    p = tmp_path / "blob.csv"
    # Path.write_text gained newline= in 3.10; the support floor is 3.9.
    with open(p, "w", newline="", encoding="utf-8") as fh:
        fh.write("a,b\n" + blob + ",1\n")

    assert main([str(p), "--no-color"]) == 0
    table = capsys.readouterr().out
    assert blob not in table
    assert max(len(line) for line in table.splitlines()) < 200

    assert main([str(p), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["columns"][0]["top"][0]["value"] == blob
