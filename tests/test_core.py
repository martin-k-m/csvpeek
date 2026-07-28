import csv

from csvpeek.core import infer_type, is_null, profile_file, profile_rows


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
