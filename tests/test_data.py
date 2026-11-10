"""--data from CSV, TSV/TXT, XLSX and JSON, with --rows, --where and --copies-from."""

import datetime as dt
import json

import openpyxl
import pytest

from bobina import cli, datasource
from bobina.engine import build_batch


def labels(tmp_path, *extra):
    doc = tmp_path / "l.bob.md"
    doc.write_text("{{ name }} {{ size }}\n")
    out = tmp_path / "o.bin"
    code = cli.main(["print", str(doc), "-o", str(out), "--force", *extra])
    return code, out.read_bytes() if out.exists() else b""


def test_delimiters_are_detected(tmp_path):
    (tmp_path / "a.txt").write_text("name;size\nRice;1kg\nBeans;500g\n", encoding="utf-8")
    (tmp_path / "b.tsv").write_text("name\tsize\nRice\t1kg\n", encoding="utf-8")
    (tmp_path / "c.csv").write_bytes("name,size\nPão,1\n".encode("cp1252"))  # Excel-on-Windows CSV
    assert [r["name"] for r in datasource.read_rows(str(tmp_path / "a.txt"))] == ["Rice", "Beans"]
    assert datasource.read_rows(str(tmp_path / "b.tsv"))[0]["size"] == "1kg"
    assert datasource.read_rows(str(tmp_path / "c.csv"))[0]["name"] == "Pão"


def test_xlsx_values_sheet_and_no_formulas(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append([])  # blank first row: the header is the first non-empty one
    ws.append(["name", "size", "when", "qty", "calc"])
    ws.append(["Rice", 1.0, dt.datetime(2026, 11, 7), 2, "=1+1"])
    wb.create_sheet("Other").append(["name"])
    wb.save(tmp_path / "s.xlsx")
    (row,) = datasource.read_rows(str(tmp_path / "s.xlsx"))
    assert row == {"name": "Rice", "size": "1", "when": "2026-11-07", "qty": "2", "calc": ""}  # formula not run
    with pytest.raises(datasource.DataError, match="sheets: Stock, Other"):
        datasource.read_rows(str(tmp_path / "s.xlsx"), sheet="Nope")
    code, data = labels(tmp_path, "--data", str(tmp_path / "s.xlsx"), "--sheet", "Stock")
    assert code == cli.OK and b"Rice 1" in data


def test_rows_where_and_copies(tmp_path):
    (tmp_path / "d.csv").write_text("name,size,qty,shelf\nRice,1kg,2,A\nBeans,500g,0,A\nSalt,1kg,1,B\nOil,900ml,3,A\n")
    d = str(tmp_path / "d.csv")
    code, data = labels(tmp_path, "--data", d, "--rows", "2-4", "--where", "shelf=a", "--copies-from", "qty")
    assert code == cli.OK
    assert data.count(b"Oil 900ml") == 3 and b"Beans" not in data and b"Salt" not in data and b"Rice" not in data
    code, data = labels(tmp_path, "--data", d, "--where", "size~=KG", "--where", "name!=salt")
    assert b"Rice" in data and b"Salt" not in data and b"Oil" not in data
    assert labels(tmp_path, "--data", d, "--where", "color=red")[0] == cli.USAGE
    assert labels(tmp_path, "--data", d, "--rows", "9-")[0] == cli.USAGE


def test_copies_are_identical_and_counters_advance_per_row():
    b = build_batch("{{ n }} #{{ seq.t }}", rows_data=[{"n": "a"}, {"n": "b"}], row_copies=[2, 1])
    assert len(b.results) == 3 and b.results[0] is b.results[1]  # a copy, not a new render
    assert b"#1" in b.results[0].data and b"#2" in b.results[2].data
    with pytest.raises(ValueError, match="1000"):
        build_batch("x", rows_data=[{}] * 20, row_copies=[60] * 20)


def test_bad_inputs_are_clear(tmp_path):
    (tmp_path / "x.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    (tmp_path / "j.json").write_text(json.dumps({"not": "a list"}))
    (tmp_path / "q.csv").write_text("name,qty\nA,lots\n")
    for f, msg in (("x.xls", "save it as .xlsx"), ("j.json", "list of objects")):
        with pytest.raises(datasource.DataError, match=msg):
            datasource.read_rows(str(tmp_path / f))
    with pytest.raises(datasource.DataError, match="not a whole number"):
        datasource.copies_per_row(datasource.read_rows(str(tmp_path / "q.csv")), "qty")


def test_xlsx_shows_what_excel_shows_for_percent_and_zero_padding(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["pct", "pct1", "zip", "plain"])
    ws.append([0.5, 0.125, 1310, 0.5])
    ws["A2"].number_format = "0%"
    ws["B2"].number_format = "0.0%"
    ws["C2"].number_format = "00000"
    wb.save(tmp_path / "f.xlsx")
    (row,) = datasource.read_rows(str(tmp_path / "f.xlsx"))
    assert row == {"pct": "50%", "pct1": "12.5%", "zip": "01310", "plain": "0.5"}


def test_excel_numbers_as_excel_shows_them(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from bobina import datasource

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["pct", "pct1", "zip", "f", "calc"])
    ws.append([0.125, 0.0125, -5, 0.1 + 0.2, "=1+1"])
    ws["A2"].number_format = "0%"
    ws["B2"].number_format = "0.0%"
    ws["C2"].number_format = "000"
    p = tmp_path / "n.xlsx"
    wb.save(p)
    notes = []
    rows = datasource.read_rows(p, None, notes)
    assert rows[0]["pct"] == "13%" and rows[0]["pct1"] == "1.3%"  # half up, like Excel
    assert rows[0]["zip"] == "-005" and rows[0]["f"] == "0.3"
    assert rows[0]["calc"] == "" and [n[0] for n in notes] == ["M160"]  # never saved by a spreadsheet app
