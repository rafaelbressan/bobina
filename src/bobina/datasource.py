"""Rows for batch printing: CSV, TSV/TXT (delimiter detected), Excel .xlsx and JSON, with a row range, filters
and per-row copies. Every value is a plain string and stays literal data (the caller marks it Tainted).

Spreadsheets are untrusted input: formulas are never evaluated (cached values only), the file and its unpacked
size are capped, and only the first rows are read.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

MAX_FILE = 20_000_000
MAX_UNPACKED = 200_000_000  # xlsx is a zip: refuse zip bombs before parsing
MAX_READ = 10_000  # rows read from the file (the batch itself stays ≤ 1000)


class DataError(ValueError):
    """code: E301 file/format, E302 no rows, E303 column/sheet, E304 invalid value."""

    def __init__(self, message: str, code: str = "E301"):
        super().__init__(message)
        self.code = code


def read_rows(path: str, sheet: str | None = None, notes: list | None = None) -> list[dict[str, str]]:
    """notes (optional) collects (code, message, hint) about columns that lose data: extra fields in a row,
    repeated headers, values under an empty header."""
    notes = notes if notes is not None else []
    p = Path(path).expanduser()
    try:
        size = p.stat().st_size
    except OSError as e:
        raise DataError(f"{path}: {e.strerror}") from None
    if size > MAX_FILE:
        raise DataError(f"{p.name}: larger than {MAX_FILE // 1_000_000} MB")
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        rows = _xlsx(p, sheet, notes)
    elif ext in (".xls", ".ods", ".numbers"):
        raise DataError(f"{p.name}: {ext} is not supported; save it as .xlsx or .csv")
    elif ext == ".json":
        rows = _json(p)
    else:
        rows = _delimited(p, "\t" if ext == ".tsv" else None, notes)
    if not rows:
        raise DataError(f"{p.name}: no rows", code="E302")
    return rows


def _text(p: Path) -> str:
    from .fileio import read_capped

    try:
        raw = read_capped(p, MAX_FILE)
    except OSError as e:
        raise DataError(f"{p.name}: {e.strerror}") from None
    if raw is None:  # a pipe or a device: no size to check before reading
        raise DataError(f"{p.name}: larger than {MAX_FILE // 1_000_000} MB")
    for enc in ("utf-8-sig", "cp1252"):  # Excel on Windows saves CSV as cp1252
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _header_notes(name: str, header: list[str], notes: list) -> None:
    from collections import Counter

    dupes = [h for h, n in Counter(h for h in header if h).items() if n > 1]
    if dupes:
        notes.append(("M154", f"{name}: the header repeats {', '.join(dupes)}; the last one is used",
                      "rename the columns"))  # fmt: skip


def _delimited(p: Path, delimiter: str | None, notes: list) -> list[dict[str, str]]:
    text = _text(p)
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    out, extra = [], []
    try:
        _header_notes(p.name, [str(h).strip() for h in (reader.fieldnames or [])], notes)
        for i, r in enumerate(reader):
            if i >= MAX_READ:
                break
            if r.get(None):
                extra.append(i + 1)
            out.append({str(k).strip(): (v or "").strip() for k, v in r.items() if k})
    except csv.Error as e:  # a value longer than 128 KB, a broken quote
        raise DataError(f"{p.name}: line {reader.line_num}: {e}") from None
    if extra:
        rows = ", ".join(map(str, extra[:5])) + (f" and {len(extra) - 5} more" if len(extra) > 5 else "")
        which = f"row {rows} has" if len(extra) == 1 else f"rows {rows} have"
        notes.append(("M153", f"{p.name}: {which} more fields than the header; the extra ones are lost",
                      f"a separator inside a value? quote it (\"a{delimiter} b\")"))  # fmt: skip
    return out


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == time(0) else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


_PCT = re.compile(r"^0(?:\.(0+))?%$")
_ZEROS = re.compile(r"^0{2,}$")


def _xcell(c) -> str:
    """An Excel cell as the person sees it: percent and zero-padded formats are applied (Excel stores
    50% as 0.5 and the zip code 01310 as 1310); everything else is the stored value."""
    v, fmt = getattr(c, "value", c), (getattr(c, "number_format", "") or "").strip()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        m = _PCT.match(fmt)
        if m:  # Excel rounds half up (0.125 at 0% shows 13%), Python's format rounds half to even (12%)
            places = len(m.group(1) or "")
            try:
                return f"{(Decimal(str(v)) * 100).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)}%"
            except InvalidOperation:  # too many digits for Decimal (1e30 at 0%): Python's formatting
                return f"{v * 100:.{places}f}%"
        if _ZEROS.match(fmt) and float(v).is_integer():
            sign = "-" if v < 0 else ""
            return sign + str(abs(int(v))).zfill(len(fmt))  # -5 at 000 is -005, as in Excel
        if isinstance(v, float) and not v.is_integer():
            short = f"{v:.15g}"  # 15 significant digits, what Excel shows: 0.1+0.2 is 0.3, not 0.30000000000000004
            return short if "e" not in short else repr(v)
    return _cell(v)


def _xlsx(p: Path, sheet: str | None, notes: list) -> list[dict[str, str]]:
    try:
        import openpyxl
    except ImportError:
        raise DataError("Excel support is not installed: pip install 'bobina[xlsx]' (or save as .csv)") from None
    try:
        with zipfile.ZipFile(p) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
                raise DataError(f"{p.name}: unpacks to more than {MAX_UNPACKED // 1_000_000} MB")
    except (zipfile.BadZipFile, OSError):  # OSError: a pipe cannot seek
        raise DataError(f"{p.name}: not a valid .xlsx file") from None
    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)  # data_only: cached values, no formulas
    except Exception as e:  # noqa: BLE001
        raise DataError(f"{p.name}: cannot read ({e.__class__.__name__})") from None
    try:
        if sheet is not None and sheet not in wb.sheetnames:
            raise DataError(f"{p.name}: no sheet '{sheet}' (sheets: {', '.join(wb.sheetnames)})", "E303")
        ws = wb[sheet] if sheet else wb.worksheets[0]
        it = ws.iter_rows()  # cells, not values: the number format is needed (see _xcell)
        header, header_idx = None, -1
        for k, row in enumerate(it):  # the first non-empty row is the header
            if any(getattr(c, "value", None) not in (None, "") for c in row):
                header, header_idx = [_xcell(c) for c in row], k
                break
        if not header:
            return []
        _header_notes(f"{p.name} [{ws.title}]", header, notes)
        lost = 0
        out = []
        blanks: set[tuple[int, int]] = set()  # (row, column) of empty cells under a header: a formula never saved?
        for r_idx, row in enumerate(it, start=header_idx + 1):
            if len(out) >= MAX_READ:
                break
            if not any(getattr(c, "value", None) not in (None, "") for c in row):
                continue
            out.append({h: _xcell(c) for h, c in zip(header, row, strict=False) if h})
            lost += sum(1 for h, c in zip(header, row, strict=False) if not h and _xcell(c))
            blanks |= {(r_idx, k) for k, (h, c) in enumerate(zip(header, row, strict=False))
                       if h and getattr(c, "value", None) is None}  # fmt: skip
        if lost:
            values = "1 value is" if lost == 1 else f"{lost} values are"
            notes.append(("M153", f"{p.name} [{ws.title}]: {values} under an empty header and are lost",
                          "give that column a header"))  # fmt: skip
        if blanks:
            unsaved = _formulas_without_value(p, ws.title, blanks)
            if unsaved:
                cells = f"{unsaved} formula cell" + ("" if unsaved == 1 else "s")
                notes.append(("M160", f"{p.name} [{ws.title}]: {cells} without a saved value print empty",
                              "open the file in Excel or LibreOffice and save it again"))  # fmt: skip
        return out
    finally:
        wb.close()


def _formulas_without_value(p: Path, title: str, blanks: set[tuple[int, int]]) -> int:
    """How many of the empty cells seen in the first read are formulas (files written by scripts and never opened
    in a spreadsheet app have no cached value). One more read, only when there were empty cells."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=False)
    except Exception:  # noqa: BLE001 - the first read worked; this is only a note
        return 0
    try:
        last = max(r for r, _ in blanks)
        n = 0
        for r_idx, row in enumerate(wb[title].iter_rows(values_only=True)):
            if r_idx > last:
                break
            n += sum(1 for k, f in enumerate(row) if (r_idx, k) in blanks and isinstance(f, str) and f.startswith("="))
        return n
    finally:
        wb.close()


def _json(p: Path) -> list[dict[str, str]]:
    try:
        data = json.loads(_text(p))
    except RecursionError:
        raise DataError(f"{p.name}: JSON nested too deeply") from None
    except ValueError as e:  # also a number of more than 4300 digits
        raise DataError(f"{p.name}: invalid JSON ({getattr(e, 'msg', e)})") from None
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise DataError(f"{p.name}: expected a list of objects")
    return [{str(k): _cell(v) for k, v in r.items()} for r in data[:MAX_READ]]


# -- selection --------------------------------------------------------------------------------------------

WHERE_RE = re.compile(r"\s*([^=!~]+?)\s*(=|!=|~=)\s*(.*)")


def row_range(spec: str, total: int) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)?\s*(?:-\s*(\d+)?)?\s*", spec or "")
    if not spec or not m or (m.group(1) is None and m.group(2) is None):
        raise DataError(
            f"--rows expects N, N-M, N- or -M (data rows, 1 = first after the header), got '{spec}'", code="E304"
        )
    a = int(m.group(1) or 1)
    b = int(m.group(2)) if m.group(2) else (total if "-" in spec else a)
    if a < 1 or b < a:
        raise DataError(f"--rows {spec}: empty range", code="E304")
    return a, min(b, total)


LINE = "\x00line"  # the row's number in its file (1 = first data row): kept through filters, never a column


def internal(key) -> bool:
    """Keys bobina keeps in a row for itself (LINE): never a column, a field name or an export name."""
    return str(key).startswith("\x00")


def columns(rows: list[dict]) -> list[str]:
    """Every column of the rows, in order of appearance (JSON objects do not all have the same keys)."""
    return list(dict.fromkeys(k for r in rows for k in r if not internal(k)))


def where_column(spec: str) -> str:
    """The column of a --where spec (COLUMN=VALUE, COLUMN!=VALUE, COLUMN~=TEXT); the spec itself when malformed."""
    m = WHERE_RE.fullmatch(spec)
    return m.group(1) if m else spec.strip()


def select(
    rows: list[dict[str, str]], *, rows_spec: str | None = None, where: list[str] | None = None
) -> list[dict[str, str]]:
    cols = columns(rows)
    if rows_spec:
        a, b = row_range(rows_spec, len(rows))
        rows = rows[a - 1 : b]
    for w in where or []:
        m = WHERE_RE.fullmatch(w)
        if not m:
            raise DataError(f"--where expects COLUMN=VALUE, COLUMN!=VALUE or COLUMN~=TEXT, got '{w}'", code="E304")
        col, op, val = m.group(1), m.group(2), m.group(3).strip()
        if col not in cols:
            raise DataError(f"--where: no column '{col}' (columns: {', '.join(cols)})", "E303")
        v = val.casefold()
        if op == "=":
            rows = [r for r in rows if r.get(col, "").strip().casefold() == v]
        elif op == "!=":
            rows = [r for r in rows if r.get(col, "").strip().casefold() != v]
        else:
            rows = [r for r in rows if v in r.get(col, "").casefold()]
    return rows


def copies_per_row(rows: list[dict[str, str]], column: str) -> list[int]:
    if rows and column not in columns(rows):
        raise DataError(f"--copies-from: no column '{column}' (columns: {', '.join(columns(rows))})", "E303")
    out = []
    for i, r in ((r.get(LINE, i), r) for i, r in enumerate(rows, 1)):  # the file's row number, as M131
        raw = r.get(column, "").strip() or "1"
        if not re.fullmatch(r"\d+(?:[.,]0+)?", raw):  # 2.9, inf, -1: not silently rounded (Excel's 2.0 is fine)
            raise DataError(f"--copies-from {column}: row {i} has '{raw}', not a whole number", code="E304")
        n = int(re.split(r"[.,]", raw)[0])
        if not 0 <= n <= 100:
            raise DataError(f"--copies-from {column}: row {i} asks {n} copies (0-100)", code="E304")
        out.append(n)
    return out


# -- several sources (--data NAME=FILE --join NAME=FILE --on KEY) ------------------------------------------

NAME_OK = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}")


def named(spec: str) -> tuple[str, str]:
    """'b=catalog.json' -> ('b', 'catalog.json'); 'catalog.json' -> ('catalog', 'catalog.json')."""
    name, sep, path = spec.partition("=")
    if sep and NAME_OK.fullmatch(name):
        return name, path
    stem = re.sub(r"[^A-Za-z0-9_]", "_", Path(spec).stem) or "data"
    return (stem if stem[0].isalpha() or stem[0] == "_" else "d_" + stem), spec


def key_spec(on: str, left: str, right: str) -> tuple[str, str]:
    """--on 'name' -> (name, name); 'a.name=b.product' or 'name=product' -> (name, product). The left side may
    name any column already in the rows ('b.id' after an earlier join); the right side is a column of the new
    source."""
    lhs, sep, rhs = on.partition("=")
    lhs = lhs.strip()
    rhs = rhs.strip() if sep else lhs
    lhs = lhs[len(left) + 1 :] if lhs.startswith(left + ".") else lhs
    rhs = rhs[len(right) + 1 :] if rhs.startswith(right + ".") else rhs
    if not sep and lhs.startswith(right + "."):
        lhs = rhs
    return lhs, rhs


def join(
    main: list[dict[str, str]], main_name: str, other: list[dict[str, str]], other_name: str, on: str
) -> tuple[list[dict[str, str]], list[tuple[str, str, str]]]:
    """Left join by key. Each row keeps its bare columns (the main source wins) and gains 'source.column'
    keys for every source. -> (rows, notes) where notes are (code, message, hint)."""
    lk, rk = key_spec(on, main_name, other_name)
    main_cols, other_cols = columns(main), columns(other)
    if main and lk not in main_cols and f"{main_name}.{lk}" not in main_cols:
        raise DataError(f"--on {on}: no column '{lk}' in {main_name} (columns: {', '.join(_bare(main_cols))})", "E303")
    if other and rk not in other_cols:
        raise DataError(f"--on {on}: no column '{rk}' in {other_name} (columns: {', '.join(other_cols)})", "E303")
    index: dict[str, dict[str, str]] = {}
    dupes: set[str] = set()
    for r in other:
        k = r.get(rk, "").strip().casefold()
        if not k:
            continue  # an empty key matches nothing (it would pair unrelated rows)
        if k in index:
            dupes.add(r.get(rk, ""))
        else:
            index[k] = r
    out, missing, clash = [], [], set()
    for r in main:
        row = dict(r)
        if not any(c.startswith(main_name + ".") for c in row):  # first join: prefixed copies of the main source
            row.update({f"{main_name}.{c}": v for c, v in r.items()})
        key = r.get(lk, r.get(f"{main_name}.{lk}", "")).strip().casefold()
        match = index.get(key) if key else None
        if match is None:
            missing.append(r.get(lk, "") or "(empty)")
        for c in other_cols:
            v = (match or {}).get(c, "")
            row[f"{other_name}.{c}"] = v
            if c in row:
                if c != rk and c != lk:
                    clash.add(c)
            else:
                row[c] = v
        out.append(row)
    notes = []
    if missing:
        shown = ", ".join(repr(m) for m in missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        rows_word = f"1 row of {main_name} has" if len(missing) == 1 else f"{len(missing)} rows of {main_name} have"
        notes.append(("M150", f"{rows_word} no match in {other_name}: {shown}",
                      f"their {other_name} fields print empty"))  # fmt: skip
    if dupes:
        notes.append(
            ("M151", f"{other_name} repeats the key {', '.join(sorted(dupes)[:5])}: the first row was used", "")
        )
    for c in sorted(clash):
        notes.append(("M152", f"'{c}' exists in {main_name} and {other_name}; {{{{ {c} }}}} uses {main_name}",
                      f"write {{{{ {other_name}.{c} }}}} for the other one", c, other_name))  # fmt: skip
        # (the column and the other source let the caller keep M152 only when the bare name is used)
    return out, notes


def _bare(cols) -> list[str]:
    return [c for c in cols if "." not in c]


def nest(row: dict[str, str], sources: set[str] | None = None) -> dict:
    """'b.category' keys -> {'b': {'category': …}} for the template, only for real source names: a column
    that merely contains a dot ('price.usd') stays a plain column."""
    out: dict = {}
    groups: dict[str, dict] = {}
    for k, v in row.items():
        src, dot, col = k.partition(".")
        if dot and sources and src in sources:
            groups.setdefault(src, {})[col] = v
        else:
            out[k] = v
    out.update(groups)  # source names never equal a column name (read_data renames or refuses)
    return out


def ident(name: str) -> str:
    """'Product Name' -> 'product_name', 'Preço' -> 'preco', '2026 total' -> 'c_2026_total'."""
    import unicodedata

    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return ("c_" + s if s[:1].isdigit() else s) or "c"


def normalize_columns(rows: list[dict], notes: list, sources: set[str] | None = None) -> tuple[list[dict], set[str]]:
    """Columns that cannot be written in {{ }} (spaces, accents, dots in a plain header…) get a usable alias
    (decided 07/11): Product Name -> product_name. The original names stay for {{ row['Product Name'] }}.
    -> (rows with aliases, the original bare column names)."""
    sources = sources or set()  # the real source names (--data/--join NAME=): only they make 'b.x' a prefix
    cols = [c for c in columns(rows) if "." not in c or c.split(".", 1)[0] not in sources]
    originals = set(cols)
    alias: dict[str, str] = {}
    taken = set(columns(rows)) | sources  # an alias never takes a source name ({{ stock }} would be the group)
    clashes = []
    for c in cols:
        a = ident(c)
        if a == c or (c.isidentifier() and c.isascii() and a == c.lower() and a in taken):
            continue
        if a in taken:
            clashes.append(f"{c} → {a}")
            continue
        alias[c] = a
        taken.add(a)
    if alias:
        shown = ", ".join(f"{c} → {a}" for c, a in list(alias.items())[:6]) + (" …" if len(alias) > 6 else "")
        notes.append(("M158", f"columns usable in {{{{ }}}} as: {shown}", "row['Original Name'] keeps the exact name"))
    if clashes:
        notes.append(("M159", f"two columns would get the same name ({', '.join(clashes)}): the first keeps it",
                      "use {{ row['Exact Name'] }} for the other"))  # fmt: skip
    if alias:
        rows = [{**r, **{a: r[c] for c, a in alias.items() if c in r}} for r in rows]
    return rows, originals
