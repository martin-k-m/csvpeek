import csv

import pytest

from csvpeek.core import ProfileError, infer_type, is_null, profile_file, profile_rows


def test_is_null():
    for tok in ["", " ", "NA", "n/a", "null", "None", "NaN", "NIL"]:
        assert is_null(tok)
    for tok in ["0", "false", "x", "-1"]:
        assert not is_null(tok)


def test_infer_type():
    assert infer_type(["1", "2", "3"]) == "int"
    assert infer_type(["1.5", "2", "3"]) == "float"
    assert infer_type(["true", "no", "Y"]) == "bool"
    assert infer_type(["a", "b", "1"]) == "string"      # one label demotes to string
    assert infer_type(["", "NA"]) == "empty"
    assert infer_type(["1", "", "3"]) == "int"          # nulls ignored for inference


def test_profile_rows_numeric_stats():
    header = ["age"]
    rows = [["10"], ["20"], ["30"], [""]]
    prof = profile_rows(header, rows)
    col = prof.columns[0]
    assert prof.rows == 4
    assert col.dtype == "int"
    assert col.count == 3 and col.nulls == 1
    assert col.minimum == 10 and col.maximum == 30
    assert col.mean == 20 and col.median == 20
    # quartiles (exclusive method): [10,20,30] -> q1=10, q3=30
    assert col.p25 == 10 and col.p75 == 30


def test_quartiles_need_two_values():
    col = profile_rows(["x"], [["5"]]).columns[0]
    assert col.p25 is None and col.p75 is None


def test_sniff_delimiter():
    from csvpeek.core import sniff_delimiter
    assert sniff_delimiter("a;b;c\n1;2;3\n4;5;6") == ";"
    assert sniff_delimiter("a\tb\n1\t2\n3\t4") == "\t"


def test_profile_file_autodetects_semicolon(tmp_path):
    p = tmp_path / "semi.csv"
    p.write_text("a;b\n1;2\n3;4\n", encoding="utf-8")
    prof = profile_file(str(p))  # no delimiter passed
    assert [c.name for c in prof.columns] == ["a", "b"]
    assert prof.rows == 2


def test_profile_rows_categorical_top_is_deterministic():
    header = ["color"]
    rows = [["red"], ["blue"], ["red"], ["green"], ["blue"], ["red"]]
    prof = profile_rows(header, rows, top_n=2)
    col = prof.columns[0]
    assert col.dtype == "string"
    assert col.unique == 3
    # red(3) then blue(2); ties broken alphabetically
    assert col.top == [("red", 3), ("blue", 2)]


def test_ragged_rows_are_padded():
    header = ["a", "b", "c"]
    rows = [["1", "2"]]  # short row
    prof = profile_rows(header, rows)
    assert prof.columns[2].nulls == 1


def test_null_pct():
    header = ["x"]
    rows = [["1"], [""], [""], ["4"]]
    col = profile_rows(header, rows).columns[0]
    assert col.nulls == 2 and col.null_pct == 50.0


def test_infer_type_date():
    assert infer_type(["2024-01-01", "2024-12-31"]) == "date"
    assert infer_type(["01/02/2024", "12/31/2024"]) == "date"
    assert infer_type(["2024-01-01T09:30:00"]) == "date"
    # bare numbers must NOT be read as dates
    assert infer_type(["2024", "2025"]) == "int"
    # one non-date value demotes to string
    assert infer_type(["2024-01-01", "sometime"]) == "string"


def test_limit_caps_rows():
    header = ["x"]
    rows = [["1"], ["2"], ["3"], ["4"], ["5"]]
    prof = profile_rows(header, rows, limit=2)
    assert prof.rows == 2
    assert prof.columns[0].count == 2


def test_limit_none_reads_all():
    header = ["x"]
    rows = [["1"], ["2"], ["3"]]
    assert profile_rows(header, rows, limit=None).rows == 3


def test_profile_file_roundtrip(tmp_path):
    p = tmp_path / "data.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "score"])
        w.writerow(["ann", "9"])
        w.writerow(["bob", "7"])
    prof = profile_file(str(p))
    assert prof.rows == 2
    assert [c.name for c in prof.columns] == ["name", "score"]
    assert prof.columns[1].dtype == "int"


def test_empty_file(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    prof = profile_file(str(p))
    assert prof.rows == 0 and prof.columns == []


def test_non_utf8_file_raises_profile_error(tmp_path):
    p = tmp_path / "latin1.csv"
    p.write_bytes("name,city\nJosé,Málaga\n".encode("cp1252"))
    with pytest.raises(ProfileError, match="not UTF-8 text"):
        profile_file(str(p))


def test_oversized_field_raises_profile_error(tmp_path):
    p = tmp_path / "big.csv"
    p.write_text("a,b\n" + "x" * (csv.field_size_limit() + 1) + ",1\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="field larger than field limit"):
        profile_file(str(p))


def test_infinity_raises_profile_error():
    # inf parses as a float, then breaks statistics and has no JSON literal.
    with pytest.raises(ProfileError, match="not a finite number"):
        profile_rows(["v"], [["1"], ["inf"]])


def test_single_infinity_raises_profile_error():
    # One value skips stdev and quantiles, so the guard cannot live there.
    with pytest.raises(ProfileError, match="not a finite number"):
        profile_rows(["v"], [["inf"]])


def test_huge_integer_that_overflows_to_inf_is_rejected():
    with pytest.raises(ProfileError, match="not a finite number"):
        profile_rows(["v"], [["1"], ["1" * 400]])


def test_finite_values_that_overflow_when_summed_are_rejected():
    # Every value is finite, so the input guard passes them. fsum raises rather
    # than returning inf, which used to escape as a traceback and exit 1.
    with pytest.raises(ProfileError, match="too large to summarise"):
        profile_rows(["v"], [["1e308"], ["1e308"]])


def test_finite_values_with_infinite_spread_are_rejected():
    # quantiles turns a finite pair into +/-Infinity, which has no JSON literal,
    # so --json used to emit output no strict parser accepts, at exit 0.
    #
    # Which guard catches it depends on the Python version, so this asserts the
    # outcome rather than the route. On 3.12 and later quantiles returns the
    # infinity and the finiteness check rejects it; on 3.10 and earlier the same
    # input raises OverflowError inside quantiles first. Both are ProfileError
    # and both exit 3, which is the contract that matters.
    with pytest.raises(ProfileError, match="not a finite number|too large to summarise"):
        profile_rows(["v"], [["1e308"], ["-1e308"]])


def test_multi_character_delimiter_is_a_user_error(tmp_path):
    # csv raises TypeError here, not csv.Error, so the CSV handler missed it.
    p = tmp_path / "d.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="single character"):
        profile_file(str(p), delimiter=";;")
