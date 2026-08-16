import io
import json
import sys

import pytest

from csvpeek.cli import main, render_markdown
from csvpeek.core import profile_rows


def _run(monkeypatch, argv, encoding):
    """Run the CLI against a stdout that encodes as ``encoding``.

    A real cp1252 console is what breaks on Windows; this reproduces it without
    needing one. Returns ``(exit_code, decoded_output)``.
    """
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding=encoding, newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    code = main(argv)
    stream.flush()
    return code, buf.getvalue().decode(encoding)


def test_render_markdown_structure():
    prof = profile_rows(["name", "age"], [["ann", "9"], ["bob", "7"]])
    md = render_markdown(prof)
    assert md.startswith("# CSV profile")
    assert "2 rows × 2 columns" in md
    assert "| Column | Type | Nulls | Unique | Summary |" in md
    assert "| `age` | int |" in md
    assert "mean" in md  # numeric summary is present


def test_markdown_escapes_pipes():
    # A value containing a pipe must not break the table.
    prof = profile_rows(["c"], [["a|b"], ["a|b"], ["x"]])
    md = render_markdown(prof)
    assert "\\|" in md
    assert "a|b (2)" not in md  # the raw pipe was escaped


def test_markdown_empty_profile():
    prof = profile_rows([], [])
    md = render_markdown(prof)
    assert "0 rows × 0 columns" in md
    assert "| Column | Type | Nulls | Unique | Summary |" in md


def test_main_format_md(capsys, tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    assert main([str(path), "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# CSV profile")
    assert "| `a` |" in out


def test_main_json_shortcut_matches_format_json(capsys, tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")

    assert main([str(path), "--json"]) == 0
    shortcut = capsys.readouterr().out

    assert main([str(path), "--format", "json"]) == 0
    explicit = capsys.readouterr().out

    assert shortcut == explicit
    assert json.loads(shortcut)["rows"] == 1


def test_json_output_carries_schema_and_integer_statistics(capsys, tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("v\n2\n4\n9\n", encoding="utf-8")

    assert main([str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == 1
    col = payload["columns"][0]
    assert col["dtype"] == "int"
    assert isinstance(col["minimum"], int) and col["minimum"] == 2
    assert isinstance(col["maximum"], int) and col["maximum"] == 9
    assert "min" not in col and "max" not in col  # the pre-1.0 spelling is gone
    assert isinstance(col["mean"], float)


def test_main_missing_file_returns_2(capsys):
    assert main(["does-not-exist.csv"]) == 2
    err = capsys.readouterr().err
    assert "file not found" in err


def test_table_falls_back_to_ascii_on_cp1252_stdout(monkeypatch, tmp_path):
    # A cp1252 console cannot encode the box rule, and used to die printing it.
    path = tmp_path / "d.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    code, out = _run(monkeypatch, [str(path), "--no-color"], "cp1252")

    assert code == 0
    assert "2 rows x 2 columns" in out
    assert "----" in out
    assert not any(ch in out for ch in "─×·")


def test_table_keeps_box_characters_on_utf8_stdout(monkeypatch, tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    code, out = _run(monkeypatch, [str(path), "--no-color"], "utf-8")

    assert code == 0
    assert "2 rows × 2 columns" in out
    assert "─" in out and " · " in out


def test_markdown_falls_back_to_ascii_on_cp1252_stdout(monkeypatch, tmp_path):
    # cp1252 can encode × and ·, but writing them there produces mojibake in a
    # Markdown file everything else reads as UTF-8.
    path = tmp_path / "d.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    code, out = _run(monkeypatch, [str(path), "--format", "md"], "cp1252")

    assert code == 0
    assert "2 rows x 2 columns" in out
    assert not any(ch in out for ch in "─×·")


def test_values_the_stream_cannot_encode_are_escaped_not_fatal(monkeypatch, tmp_path):
    path = tmp_path / "cjk.csv"
    path.write_text("name\n東京\n大阪\n", encoding="utf-8")

    code, out = _run(monkeypatch, [str(path), "--no-color"], "cp1252")

    assert code == 0
    assert "\\u6771\\u4eac" in out


def test_non_utf8_file_exits_3(capsys, tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("name,city\nJosé,Málaga\n".encode("cp1252"))

    assert main([str(path)]) == 3
    err = capsys.readouterr().err
    assert "is not UTF-8 text" in err
    assert "0xe9" in err


def test_oversized_field_exits_3(capsys, tmp_path, squeezed_field_limit):
    path = tmp_path / "big.csv"
    path.write_text("a,b\n" + "x" * (squeezed_field_limit + 1) + ",1\n", encoding="utf-8")

    assert main([str(path)]) == 3
    err = capsys.readouterr().err
    assert "could not be parsed as CSV" in err
    assert "field larger than field limit" in err


@pytest.mark.parametrize("value", ["inf", "-Infinity", "1e999"])
def test_non_finite_value_exits_3(capsys, tmp_path, value):
    path = tmp_path / "inf.csv"
    path.write_text(f"v\n1\n{value}\n", encoding="utf-8")

    assert main([str(path), "--json"]) == 3
    err = capsys.readouterr().err
    assert "column 'v' contains a value that is not a finite number" in err


def test_near_miss_appears_in_the_table(capsys, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("qty\n1\n2\n3\ntwelve\n", encoding="utf-8")
    assert main([str(f), "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "mostly int" in out
    # Quoted, because the value is arbitrary text in a comma-separated list.
    assert '"twelve"' in out


def test_a_capped_outlier_list_says_it_is_capped(capsys, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("v\n1\n2\n3\n4\n5\n6\na\nb\nc\nd\n", encoding="utf-8")
    assert main([str(f), "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "4 not:" in out
    # A truncated list that looks complete is worse than no list.
    assert "…" in out


def test_the_capped_marker_has_an_ascii_form():
    # --no-color turns off colour, not glyphs: those are chosen by what the
    # output stream can encode. A cp1252 console gets ASCII_GLYPHS, and the
    # marker has to survive that or printing raises instead of degrading.
    from csvpeek.cli import ASCII_GLYPHS, _column_summary
    from csvpeek.core import profile_rows

    rows = [[str(i)] for i in range(6)] + [["a"], ["b"], ["c"], ["d"]]
    col = profile_rows(["v"], rows).columns[0]
    line = _column_summary(col, ASCII_GLYPHS)
    assert "..." in line
    assert "…" not in line
