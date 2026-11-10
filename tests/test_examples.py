"""The batch guide (docs/guides/batch-printing.md) shows real output: keep its examples working."""

from pathlib import Path

from bobina import datasource
from bobina.engine import build_batch
from bobina.templating import Tainted

EX = Path(__file__).resolve().parents[1] / "examples" / "batch"


def batch(data: str, **sel):
    rows = datasource.select(datasource.read_rows(str(EX / data)), **{k: v for k, v in sel.items() if k != "copies"})
    copies = datasource.copies_per_row(rows, sel["copies"]) if sel.get("copies") else None
    rows = [{k: Tainted(v) for k, v in r.items()} for r in rows]
    return build_batch((EX / "jar-label.bob.md").read_text(), rows_data=rows, row_copies=copies, base_dir=str(EX))


def test_csv_and_json_give_the_same_four_labels():
    a, b = batch("pantry.csv"), batch("pantry.json")
    assert len(a.results) == len(b.results) == 4
    assert a.data == b.data
    assert b"Best before" not in a.results[3].data  # Salt has no best_before


def test_shelf_a_one_label_per_jar():
    b = batch("pantry.json", where=["shelf=A"], copies="jars")
    names = [r.data.split(b"\n")[0][-12:] for r in b.results]
    assert len(b.results) == 3 and b"Brown rice" in names[0] and b"Brown rice" in names[1]
