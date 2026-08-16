"""Coverage for the two additions: the numeric histogram and column selection.

Kept in its own file so the new behaviour is easy to find next to the existing
suites.
"""

import json

import pytest

from csvpeek.cli import (
    ASCII_GLYPHS,
    UNICODE_GLYPHS,
    _column_summary,
    _sparkline,
    main,
)
from csvpeek.core import (
    HIST_BINS,
    Histogram,
    ProfileError,
    _histogram,
    profile_rows,
)

# --- histogram binning ------------------------------------------------------


def test_identical_values_collapse_to_a_single_bin():
    h = _histogram([5.0, 5.0, 5.0])
    assert h.counts == [3]
    assert h.edges == [5.0, 5.0]


def test_single_value_is_one_bin_of_one():
    h = _histogram([42.0])
    assert h.counts == [1]
    assert h.edges == [42.0, 42.0]


def test_a_uniform_spread_fills_every_bin_evenly():
    # 1..10, one each. With ten bins the max lands in the last bin and the rest
    # fall one per bin, so every bin holds exactly one value.
    h = _histogram([float(i) for i in range(1, 11)])
    assert len(h.counts) == HIST_BINS
    assert h.counts == [1] * HIST_BINS
    assert sum(h.counts) == 10


def test_every_value_can_land_in_one_bin_despite_a_range():
    # Nine values clustered at the bottom, one at the top. The cluster shares the
    # first bin and the lone high value takes the last; the counts still sum to
    # the input size and edges bracket the true range.
    h = _histogram([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 100.0])
    assert h.counts[0] == 9
    assert h.counts[-1] == 1
    assert sum(h.counts) == 10
    assert h.edges[0] == 0.0 and h.edges[-1] == 100.0


def test_edges_have_one_more_entry_than_counts():
    h = _histogram([1.0, 2.0, 3.0, 4.0])
    assert len(h.edges) == len(h.counts) + 1


def test_the_maximum_value_lands_in_the_last_bin_not_off_the_end():
    # The top edge is closed, so the maximum is counted rather than dropped.
    h = _histogram([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert sum(h.counts) == 11
    assert h.counts[-1] >= 1


def test_binning_is_deterministic():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    assert _histogram(values).counts == _histogram(values).counts


def test_an_integer_column_gets_a_histogram_on_the_profile():
    col = profile_rows(["v"], [[str(i)] for i in range(1, 11)]).columns[0]
    assert col.dtype == "int"
    assert isinstance(col.histogram, Histogram)
    assert sum(col.histogram.counts) == 10


def test_a_float_column_gets_a_histogram_with_the_same_bin_count():
    col = profile_rows(["v"], [["1.0"], ["2.5"], ["3.0"], ["4.5"]]).columns[0]
    assert col.dtype == "float"
    assert len(col.histogram.counts) == HIST_BINS


def test_integers_and_floats_over_the_same_values_bin_identically():
    ints = profile_rows(["v"], [[str(i)] for i in range(1, 11)]).columns[0]
    floats = profile_rows(["v"], [[f"{i}.0"] for i in range(1, 11)]).columns[0]
    assert ints.histogram.counts == floats.histogram.counts


def test_a_text_column_has_no_histogram():
    col = profile_rows(["c"], [["red"], ["blue"], ["red"]]).columns[0]
    assert col.histogram is None


def test_a_bool_column_has_no_histogram():
    col = profile_rows(["flag"], [["0"], ["1"], ["1"]]).columns[0]
    assert col.dtype == "bool"
    assert col.histogram is None


def test_nulls_do_not_reach_the_histogram():
    # Two nulls, three numbers: the bins count only the three present values.
    col = profile_rows(["v"], [["1"], [""], ["2"], ["NA"], ["3"]]).columns[0]
    assert sum(col.histogram.counts) == 3


# --- sparkline rendering ----------------------------------------------------


def test_sparkline_maps_extremes_to_top_and_bottom_glyphs():
    line = _sparkline([0, 10], UNICODE_GLYPHS.bars)
    assert line[0] == UNICODE_GLYPHS.bars[0]
    assert line[-1] == UNICODE_GLYPHS.bars[-1]


def test_sparkline_length_matches_bin_count():
    assert len(_sparkline([1, 2, 3, 4, 5], UNICODE_GLYPHS.bars)) == 5


def test_sparkline_all_zero_bins_render_as_the_bottom_glyph():
    assert _sparkline([0, 0, 0], UNICODE_GLYPHS.bars) == UNICODE_GLYPHS.bars[0] * 3


# --- histogram in each output format ----------------------------------------


def test_histogram_appears_in_the_table(capsys, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("v\n" + "\n".join(str(i) for i in range(1, 11)) + "\n", encoding="utf-8")
    assert main([str(f), "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "hist " in out
    assert any(ch in out for ch in UNICODE_GLYPHS.bars)


def test_histogram_appears_in_markdown(capsys, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("v\n" + "\n".join(str(i) for i in range(1, 11)) + "\n", encoding="utf-8")
    assert main([str(f), "--format", "md"]) == 0
    out = capsys.readouterr().out
    assert "hist " in out


def test_histogram_falls_back_to_ascii_on_cp1252():
    # --no-color leaves the glyphs to what the stream can encode. On a console
    # that cannot take the block characters the bars are ASCII, so printing
    # degrades rather than raising.
    col = profile_rows(["v"], [[str(i)] for i in range(1, 11)]).columns[0]
    line = _column_summary(col, ASCII_GLYPHS)
    assert "hist " in line
    assert not any(ch in line for ch in UNICODE_GLYPHS.bars)


def test_histogram_in_json_carries_edges_and_counts(capsys, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("v\n" + "\n".join(str(i) for i in range(1, 11)) + "\n", encoding="utf-8")
    assert main([str(f), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    col = payload["columns"][0]
    assert "histogram" in col
    assert col["histogram"]["counts"] == [1] * HIST_BINS
    assert len(col["histogram"]["edges"]) == HIST_BINS + 1
    assert col["histogram"]["edges"][0] == 1 and col["histogram"]["edges"][-1] == 10


def test_json_histogram_is_null_for_a_text_column(capsys, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("c\nred\nblue\nred\n", encoding="utf-8")
    assert main([str(f), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["columns"][0]["histogram"] is None


# --- JSON backward compatibility --------------------------------------------


def test_to_dict_default_is_unchanged_and_carries_no_histogram():
    # The default payload is byte-for-byte the pre-existing shape, so schema
    # stays 1 and old consumers are untouched.
    payload = profile_rows(["v"], [["1"], ["2"], ["3"]]).to_dict()
    assert payload["schema"] == 1
    assert "histogram" not in payload["columns"][0]


def test_to_dict_histograms_adds_only_the_one_key():
    prof = profile_rows(["v"], [["1"], ["2"], ["3"]])
    base = prof.to_dict()
    withhist = prof.to_dict(histograms=True)
    assert withhist["schema"] == base["schema"] == 1
    extra = set(withhist["columns"][0]) - set(base["columns"][0])
    assert extra == {"histogram"}


# --- column selection -------------------------------------------------------


def test_select_profiles_only_the_named_columns_in_order():
    prof = profile_rows(["a", "b", "c"], [["1", "x", "2"]], select=["c", "a"])
    assert [col.name for col in prof.columns] == ["c", "a"]


def test_select_none_profiles_everything():
    prof = profile_rows(["a", "b"], [["1", "2"]])
    assert [col.name for col in prof.columns] == ["a", "b"]


def test_select_keeps_the_right_values_with_each_column():
    prof = profile_rows(["a", "b"], [["red", "9"], ["red", "7"]], select=["b", "a"])
    assert prof.columns[0].name == "b" and prof.columns[0].dtype == "int"
    assert prof.columns[1].name == "a" and prof.columns[1].top == [("red", 2)]


def test_unknown_column_raises_profile_error():
    with pytest.raises(ProfileError, match="no such column: 'z'"):
        profile_rows(["a", "b"], [["1", "2"]], select=["a", "z"])


def test_select_still_counts_all_rows():
    # Selection narrows columns, not rows: the row count is the whole file.
    prof = profile_rows(["a", "b"], [["1", "2"], ["3", "4"]], select=["a"])
    assert prof.rows == 2
    assert prof.columns[0].count == 2


def test_cli_columns_happy_path(capsys, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("a,b,c\n1,x,2\n3,y,4\n", encoding="utf-8")
    assert main([str(f), "--json", "--columns", "c,a"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [col["name"] for col in payload["columns"]] == ["c", "a"]
    assert payload["rows"] == 2


def test_cli_columns_tolerates_spaces_after_commas(capsys, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("a,b,c\n1,x,2\n", encoding="utf-8")
    assert main([str(f), "--json", "--columns", "a, c"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [col["name"] for col in payload["columns"]] == ["a", "c"]


def test_cli_unknown_column_exits_3(capsys, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    assert main([str(f), "--columns", "a,nope"]) == 3
    err = capsys.readouterr().err
    assert "no such column: 'nope'" in err


def test_cli_empty_columns_value_is_a_usage_error(capsys, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    assert main([str(f), "--columns", " , "]) == 2
    assert "at least one column" in capsys.readouterr().err


# --- selection combined with the histogram ----------------------------------


def test_select_a_numeric_column_still_gets_its_histogram(capsys, tmp_path):
    f = tmp_path / "s.csv"
    rows = "\n".join(f"{i},{i}" for i in range(1, 11))
    f.write_text("keep,drop\n" + rows + "\n", encoding="utf-8")
    assert main([str(f), "--json", "--columns", "keep"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["columns"]) == 1
    col = payload["columns"][0]
    assert col["name"] == "keep"
    assert sum(col["histogram"]["counts"]) == 10
