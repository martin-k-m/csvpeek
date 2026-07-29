import json

from csvpeek.cli import main, render_markdown
from csvpeek.core import profile_rows


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


def test_main_missing_file_returns_2(capsys):
    assert main(["does-not-exist.csv"]) == 2
    err = capsys.readouterr().err
    assert "file not found" in err
