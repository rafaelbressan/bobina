"""Charts drawn from a table: `{chart=line|bar|area|sparkline}` on the line under a Markdown table prints it as a chart
instead of the table (`.with-table`: the table too, under the chart). `data=FILE` takes the rows from a CSV, TSV,
XLSX or JSON file (datasource.py: its limits and its rules); without chart= they print as a table. The long form is
docs/guides/charts.md.

The table is always the data: its first column the labels (X), each next column a series, the title row their names.
A file's cells are data: they become plain Runs, never Markdown, a placeholder or an icon."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from . import datasource, icons, imaging, rasterfont, templating
from .model import Attrs, Run, Table
from .nudges import SecurityError
from .rows import BitmapRow, FeedRow

TYPES = ("line", "bar", "area", "sparkline")
KEYS = frozenset({"chart", "data", "aggregate", "last", "y-ticks", "y-labels", "x-labels", "title", "length"})
CLASSES = frozenset({"grid", "no-axes", "with-table"})
TABLE_TOO = frozenset({"data", "last"})  # what a table without chart= takes too: its rows from a file, the last N
DATA_EXT = (".csv", ".tsv", ".txt", ".xlsx", ".json")
AGGREGATES = {"sum": "summed", "max": "combined (the largest kept)", "mean": "averaged"}
STROKE = 2  # every line of a chart: thinner prints broken (B101)
GAP = 4  # dots between a label and what it names
TICK = 3  # dots of a tick mark beside an axis
RATIO = 0.6  # the default height: the chart's width times this
MIN_PLOT = 24  # dots of drawing a chart keeps between its labels; less: fewer or smaller labels (C105)
NOT_NUMBER_SAID = 3  # rows left out that are named one by one (C103); the others in one line
DASHES = ((), (8, 4), (2, 4), (8, 3, 2, 3))  # a line series' pattern (on, off, …): solid, dashed, dotted, dash-dot
TYPES_HINT = "chart=line, bar, area or sparkline (docs/guides/charts.md)"
NOT_CHART = (
    'add chart=line|bar|area|sparkline to draw the table as a chart; y-ticks=, x-labels=, title="…", .grid and '
    ".no-axes are for charts"
)


def claims(t: Table) -> bool:
    """A table this module lays out: one with chart=, data= or a chart's attribute under it."""
    return bool(set(t.attrs.kv) & KEYS or t.attrs.classes & CLASSES)


@dataclass
class Source:
    titles: list[str]  # the title row's text: the labels' column first, then each series
    rows: list[tuple[list[str], int, str]]  # (cells, line in the document, where in a file: "sales.csv row 7" or "")
    machine: bool = False  # a JSON or XLSX file: its numbers are a program's (1.234 is 1.234 in any locale)


def table_block(lay, t: Table, indent: int) -> list:
    """The rows of a table with chart=, data= or a chart's attribute: a chart, a chart and the table, or the table
    (filled from the file)."""
    a = t.attrs
    src = typed(lay, t)
    if "data" in a.kv:
        if t.rows:
            lay.n.add("M101", "a table with data= takes its rows from the file: the rows written in it are left out",
                      lay.said_at(t, "data="), "keep only the title row and the --- line")  # fmt: skip
        src = from_file(lay, t, src)
        t = replace(t, rows=[[[Run(c)] if c else [] for c in cells] for cells, _, _ in src.rows],
                    row_lines=[ln for _, ln, _ in src.rows], cells=[], row_attrs=[])  # fmt: skip
    kind = a.kv.get("chart")
    if kind is None:
        idle = sorted({*(f"{k}=" for k in set(a.kv) & (KEYS - TABLE_TOO)), *(f".{c}" for c in a.classes & CLASSES)})
        if idle:
            lay.n.add("M101", f"{', '.join(idle)} {'works' if len(idle) == 1 else 'work'} with chart= only",
                      lay.said_at(t, idle[0]), NOT_CHART)  # fmt: skip
        return lay.table(last_rows(lay, plain(t, False)), indent)
    if kind not in TYPES:
        at = lay.said_at(t, "chart=")
        if kind.lower() in TYPES:
            lay.n.add("M101", f"chart={kind}: values are lowercase", at, f"write chart={kind.lower()}")
            kind = kind.lower()
        else:
            lay.n.add("M101", f"chart={kind}: not a chart type; the table printed as a table", at, TYPES_HINT)
            return lay.table(last_rows(lay, plain(t, True)), indent)
    if not a.has("with-table"):
        idle = [*(["style="] if "style" in a.kv else []),
                *(f".{c}" for c in ("compact", "bold", "italic", "underline") if a.has(c))]  # fmt: skip
        if idle:
            lay.n.add("M101", f"{', '.join(idle)} {'is' if len(idle) == 1 else 'are'} for the table, and the chart "
                      "prints instead of it", lay.said_at(t, idle[0]), "add .with-table to print the table under the "
                      "chart")  # fmt: skip
    chart = Chart(lay, t, kind, src, indent)
    rows = chart.rows()
    if rows is None:  # nothing to draw (C106, C105): the table as it is
        return lay.table(last_rows(lay, plain(t, True)), indent)
    if a.has("with-table") and rows:
        under = plain(t, True)
        if chart.kept is not None:  # last=N: the rows of the points the chart kept, not the last N rows
            under = only_rows(under, chart.kept)
        rows += [FeedRow(int(lay.p.get("margins.block_gap_dots", 12))), *lay.table(last_rows(lay, under), indent)]
    return rows


def only_rows(t: Table, keep: list[int]) -> Table:
    """The table with only these rows (by index), last= taken off: it was applied to the chart's points."""
    pick = [i for i in keep if i < len(t.rows)]

    def of(items: list) -> list:
        return [items[i] for i in pick if i < len(items)]

    attrs = Attrs(t.attrs.classes, {k: v for k, v in t.attrs.kv.items() if k != "last"})
    return replace(t, attrs=attrs, rows=of(t.rows), row_lines=of(t.row_lines), cells=of(t.cells),
                   row_attrs=of(t.row_attrs))  # fmt: skip


def plain(t: Table, chart: bool) -> Table:
    """The table without what only a chart takes (and, under a chart, without its size and place: width= height=
    orientation= are the chart's), for Layout.table."""
    drop = KEYS - {"last"} | ({"width", "height", "orientation"} if chart else set())
    return replace(t, attrs=Attrs(t.attrs.classes - CLASSES, {k: v for k, v in t.attrs.kv.items() if k not in drop}))


def last_rows(lay, t: Table) -> Table:
    """last=N on a table that prints: only its last N rows."""
    n = count(lay, t, "last", 1)
    a = Attrs(t.attrs.classes, {k: v for k, v in t.attrs.kv.items() if k != "last"})
    if n is None or n >= len(t.rows):
        return replace(t, attrs=a)
    return replace(t, attrs=a, rows=t.rows[-n:], row_lines=t.row_lines[-n:], cells=t.cells[-n:] if t.cells else [],
                   row_attrs=t.row_attrs[-n:] if t.row_attrs else [])  # fmt: skip


def count(lay, t: Table, key: str, least: int, most: int = 1_000_000) -> int | None:
    """key=N, a whole number from least to most; None when absent or unreadable (M101)."""
    given = t.attrs.kv.get(key)
    if given is None:
        return None
    try:
        n = int(str(given).strip())
        if not least <= n <= most:
            raise ValueError
    except ValueError:
        lay.n.add("M101", f"{key}={given}", lay.said_at(t, f"{key}="), f"a whole number from {least} to {most}")
        return None
    return n


def cell_text(lay, runs) -> str:
    return lay.text("".join(r.text for r in runs)).strip()


def typed(lay, t: Table) -> Source:
    rows_at = [*t.row_lines, *[t.line] * (len(t.rows) - len(t.row_lines))]
    rows = [([cell_text(lay, c) for c in r], at, "") for r, at in zip(t.rows, rows_at, strict=True)]
    return Source([cell_text(lay, c) for c in t.header], rows)


# ------------------------------------------------------------------------------------------------ data= files


def clean(value) -> str:
    """A file's cell as plain text: no printer controls, no line breaks, none of bobina's own marks (a placeholder
    would point at another value), no icon."""
    s = templating.RESERVED_CHARS.sub("", str(value))
    s = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", s)
    return icons.strip(s).strip()


def from_file(lay, t: Table, src: Source) -> Source:
    """The table's rows from its data= file: each title picks the file's column of that name (an empty title, the
    column in its place). A title the file does not have: C108, with the file's columns."""
    line = lay.said_at(t, "data=")
    got = read(lay, t.attrs.kv["data"], line)
    if got is None:
        return Source(src.titles, [])
    name, cols, rows = got
    pick: list[int | None] = []
    missing = []
    for i, title in enumerate(src.titles):
        if not title:
            pick.append(i if i < len(cols) else None)
            continue
        idx = next((k for k, c in enumerate(cols) if c == title), None)
        if idx is None:
            idx = next((k for k, c in enumerate(cols) if datasource.ident(c) == datasource.ident(title)), None)
        if idx is None:
            missing.append(title)
        pick.append(idx)
    if missing:
        shown = ", ".join(cols[:12]) + (" …" if len(cols) > 12 else "")
        lay.n.add("C108", f"{name} has no column {', '.join(repr(m) for m in missing)} (its columns: {shown})", line,
                  "write each title as a column of the file; the first title is the labels' column")  # fmt: skip
    out = [([clean(r.get(cols[k], "")) if k is not None else "" for k in pick], line, f"{name} row {n}")
           for n, r in enumerate(rows, 1)]  # fmt: skip
    return Source(src.titles, out, Path(name).suffix.lower() in (".json", ".xlsx", ".xlsm"))


def read(lay, raw: str, line: int) -> tuple[str, list[str], list[dict]] | None:
    """(file name, its columns, its rows) of data=PATH, relative to the document; None, said (C109), when it cannot
    be read. A path that comes from --data or --set must name a data file in the document's folder (M312
    otherwise: a value never chooses any other file); under --sandbox every path stays in the allowed folders."""
    tainted = lay.r is not None and lay.r.tainted_in(raw)
    text = lay.text(str(raw)).strip()
    if not text:
        lay.n.add("M101", "data= names no file", line, "data=sales.csv (relative to the document)")
        return None
    name = Path(text).name or text
    if re.match(r"^[a-z][a-z0-9+.-]+:", text, re.I):  # https:, file:, data: (a Windows drive letter is one char)
        lay.n.add("C109", f"data={text[:60]}: only a file next to the document is read", line,
                  "save it as a .csv or .xlsx file and write its path")  # fmt: skip
        return None
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = Path(lay.doc.base_dir) / p
    if tainted:
        base = Path(lay.doc.base_dir).expanduser().resolve()
        try:
            real = p.resolve()
        except (OSError, RuntimeError):
            real = p
        if not real.is_relative_to(base) or real.suffix.lower() not in DATA_EXT:
            raise SecurityError("M312", f"data={name}: a path from --data/--set must be a {'/'.join(DATA_EXT)} file "
                                "in the document's folder", line)  # fmt: skip
    if lay.image_dirs is not None:
        try:
            real = p.resolve()
        except (OSError, RuntimeError):
            real = None
        if real is None or not any(real.is_relative_to(d) for d in lay.image_dirs):
            lay.n.add("C109", f"data={name}: outside the document folder and image_dirs: not read (--sandbox)", line,
                      "put the file next to the document")  # fmt: skip
            return None
    notes: list = []
    try:
        rows = datasource.read_rows(str(p), notes=notes)
    except datasource.DataError as e:
        lay.n.add("C109", f"data={text[:60]}: {e}", line, "a CSV, TSV, XLSX or JSON file, its path relative to the "
                  "document")  # fmt: skip
        return None
    except Exception as e:  # noqa: BLE001 - a damaged spreadsheet: said, the rest prints
        lay.n.add("C109", f"data={text[:60]}: {e.__class__.__name__}", line, "save it again as .csv or .xlsx")
        return None
    for code, msg, hint, *_ in notes:
        lay.n.add(code, f"{name}: {msg}", line, hint)
    return name, datasource.columns(rows), rows


# ------------------------------------------------------------------------------------------------ numbers, dates


def decimal_of(lay) -> str:
    loc = getattr(lay.locale, "locale", None)
    if loc is None:
        return "."
    from babel import numbers

    return numbers.get_decimal_symbol(loc)


def short(v: float, decimal: str = ".") -> str:
    """A tick value written short: 300K, 1.2M, 0.5, -1.5 (in the locale's decimal sign)."""
    a = abs(v)
    x, unit = v, ""
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            x, unit = v / div, suffix
            break
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return ("0" if s in ("-0", "") else s).replace(".", decimal) + unit


def nice_up(x: float) -> float:
    """The round number at or above x: 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8 times a power of ten."""
    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    return next(m * p for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * p >= x * (1 - 1e-9))


def ticks(vmin: float, vmax: float, n: int, zero: bool, wider: int = 0) -> tuple[list[float], float, float]:
    """(n round tick values, the axis' low and high end) for values from vmin to vmax; zero: the axis reaches 0;
    wider: that many round steps wider apart (labels that do not fit between the closest ones)."""
    lo, hi = (min(vmin, 0.0), max(vmax, 0.0)) if zero else (vmin, vmax)
    if hi <= lo:
        pad = abs(lo) * 0.1 or 1.0
        lo, hi = (lo, lo + pad) if zero and lo == 0 else (lo - pad, hi + pad)
    if n < 1:
        return [], lo, hi
    if n == 1:
        return [round(lo, 10)], lo, hi
    step = nice_up((hi - lo) / n)
    for _ in range(wider):
        step = nice_up(step * 1.01)
    first = math.floor(lo / step + 1e-9) * step
    out = [round(first + i * step, 10) for i in range(n)]
    return out, min(lo, out[0]), max(hi, out[-1])


EN_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
EN_WIDE = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")  # fmt: skip


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().strip().rstrip("."))
    return "".join(c for c in s if not unicodedata.combining(c))


def month_names(loc) -> dict[str, int]:
    """Month names a label may use: English always, and the document's locale's (abbreviated and wide)."""
    out = {m: i for i, m in enumerate(EN_MONTHS, 1)} | {m: i for i, m in enumerate(EN_WIDE, 1)}
    out["sept"] = 9
    if loc is not None:
        from babel import dates

        for width in ("abbreviated", "wide"):
            for context in ("format", "stand-alone"):
                for i, nm in dates.get_month_names(width, context, locale=loc).items():
                    out.setdefault(_plain(nm), i)
    return out


ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?")
NUMERIC = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?|(\d{1,2})[.-](\d{1,2})[.-](\d{4})")
DAY_MONTH = re.compile(r"(\d{1,2})\.?\s*(?:de\s+)?([^\W\d_]+)\.?(?:,?\s*(?:de\s+)?(\d{4}))?")
MONTH_DAY = re.compile(r"([^\W\d_]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?")
MONTH_YEAR = re.compile(r"([^\W\d_]+)\.?\s*[/ -]?\s*(\d{4})")


def parse_dates(labels: list[str], loc) -> list[date] | None:
    """Every label as a date (2026-11-07, 27/01, 27/01/2026, Jan 27, 27 jan, jan/2026, in English or the locale's
    month names), or None when one is not. Without a year: 2000, and the next year when a date falls more than half
    a year before the one above it (Dec 20, Jan 5)."""
    if len(labels) < 2 or not all(labels):
        return None
    months = month_names(loc)
    us = loc is not None and getattr(loc, "territory", None) == "US"
    out: list[date] = []
    for label in labels:
        d = _one_date(label.strip(), months, us)
        if d is None:
            return None
        day, has_year = d
        if out and not has_year and day < out[-1] and (out[-1] - day).days > 183:
            try:
                while day < out[-1]:
                    day = day.replace(year=day.year + 1)
            except ValueError:  # Feb 29 in the year after: no such day, so these labels are not dates
                return None
        out.append(day)
    return out


def _one_date(s: str, months: dict[str, int], us: bool) -> tuple[date, bool] | None:
    try:
        if m := ISO.fullmatch(s):
            return date(int(m[1]), int(m[2]), int(m[3])), True
        if m := NUMERIC.fullmatch(s):
            a, b, y = (m[1], m[2], m[3]) if m[1] else (m[4], m[5], m[6])
            a, b = int(a), int(b)
            day, month = (b, a) if (us and b <= 31 and a <= 12) or a > 31 else (a, b)
            if month > 12 and day <= 12:
                day, month = month, day
            year = int(y) + (2000 if y and len(y) == 2 else 0) if y else 2000
            return date(year, month, day), bool(y)
        if (m := DAY_MONTH.fullmatch(s)) and _plain(m[2]) in months:
            return date(int(m[3] or 2000), months[_plain(m[2])], int(m[1])), bool(m[3])
        if (m := MONTH_DAY.fullmatch(s)) and _plain(m[1]) in months:
            return date(int(m[3] or 2000), months[_plain(m[1])], int(m[2])), bool(m[3])
        if (m := MONTH_YEAR.fullmatch(s)) and _plain(m[1]) in months:
            return date(int(m[2]), months[_plain(m[1])], 1), True
    except ValueError:  # 31/02, month 13
        return None
    return None


# ------------------------------------------------------------------------------------------------ the chart


@dataclass
class Point:
    label: str
    values: list[float | None]
    line: int
    x: float = 0.0
    rows: tuple[int, ...] = ()  # the source rows it stands for (.with-table with last= prints only those)


@dataclass
class Font:
    path: str
    px: int
    name: str = ""

    def __post_init__(self):
        self.f = rasterfont.load(self.path, self.px)
        asc, desc = self.f.getmetrics()
        self.h = asc + desc

    def width(self, s: str) -> int:
        return math.ceil(self.f.getlength(s))

    def image(self, s: str) -> Image.Image:
        im = Image.new("1", (max(1, self.width(s)), self.h), 1)
        ImageDraw.Draw(im).text((0, 0), s, font=self.f, fill=0)
        return im


@dataclass
class Label:
    """A text drawn in the chart, where the terminal view writes it as text: (x, y, w, h) in the chart's dots."""

    text: str
    box: tuple[int, int, int, int]
    turned: bool = False
    kind: str = "y"  # title, y, x (under the X axis), legend (under the X labels): the view keeps them in order
    rank: int = 0  # a legend's row


@dataclass
class Geo:
    font: Font
    nticks: int
    tick_values: list[float]
    lo: float
    hi: float
    left: int  # the Y axis' x (its 2 dots start here)
    plot: tuple[int, int, int, int]  # x0, y0, x1, y1 of the data
    ok: bool
    title_h: int = 0
    legend_h: int = 0
    legend: list = field(default_factory=list)  # rows of (x, item) of the legend


class Chart:
    def __init__(self, lay, t: Table, kind: str, src: Source, indent: int):
        self.lay, self.t, self.kind, self.src, self.indent = lay, t, kind, src, indent
        self.a, self.n = t.attrs, lay.n
        self.decimal = decimal_of(lay)
        self.axes = kind != "sparkline" and not self.a.has("no-axes")
        self.labels_drawn: list[Label] = []
        self.kept: list[int] | None = None  # with last=N: the source rows of the points kept

    def at(self, name: str) -> int:
        return self.lay.said_at(self.t, name)

    # ------------------------------------------------------------------ data
    def rows(self) -> list | None:
        names = self.src.titles[1:]
        if not names:
            self.n.add("C106", f"chart={self.kind}: the table has no value column: printed as a table", self.t.line,
                       "the first column holds the labels, each next column a series of numbers")  # fmt: skip
            return None
        self.names = names
        points = self.read()
        if not self.values(points):
            if self.src.rows:
                self.n.add("C106", f"chart={self.kind}: no row has a number to draw: printed as a table", self.t.line,
                           "write the values as numbers: 1234.5, or 1.234,50 with locale: pt-BR")  # fmt: skip
                return None
            return []  # no rows at all (a file that could not be read: C109 said it)
        points = self.combine(points)
        n = count(self.lay, self.t, "last", 1)
        if n is not None:
            points = points[-n:]
            self.kept = sorted(i for p in points for i in p.rows)
        self.dates = self.place(points)
        return self.draw(points)

    def read(self) -> list[Point]:
        out, left = [], []
        for k, (cells, line, where) in enumerate(self.src.rows):
            label = cells[0] if cells else ""
            values: list[float | None] = []
            bad = None
            for i in range(1, len(self.src.titles)):
                txt = cells[i].strip() if i < len(cells) else ""
                if not txt:
                    values.append(None)
                    continue
                v = machine_number(txt) if self.src.machine else None
                v = templating.parse_number(txt, self.decimal) if v is None else v
                if v is None or not math.isfinite(float(v)):
                    bad = txt
                    break
                values.append(float(v))
            if bad is not None:
                left.append((bad, label, line, where))
                continue
            if label or any(v is not None for v in values):  # a label with empty cells: a gap at its place
                out.append(Point(label, values, line, rows=(k,)))
        for bad, label, line, where in left[:NOT_NUMBER_SAID]:
            row = f"{where}: " if where else ""
            self.n.add("C103", f"{row}'{bad[:30]}' is not a number: the row '{label[:30]}' is left out of the chart",
                       line, "write digits: 1234.5, or 1.234,50 with locale: pt-BR in the front matter")  # fmt: skip
        if len(left) > NOT_NUMBER_SAID:
            more = len(left) - NOT_NUMBER_SAID
            self.n.add("C103", f"{more} more row{'s' if more > 1 else ''} with a value that is not a number left out",
                       left[NOT_NUMBER_SAID][2], "bobina check lists the first ones")  # fmt: skip
        return out

    def aggregate(self) -> str:
        how = str(self.a.kv.get("aggregate", "sum"))
        if how not in AGGREGATES:
            self.n.add("M101", f"aggregate={how}", self.at("aggregate="), "sum (the default), max or mean")
            return "sum"
        return how

    def combine(self, points: list[Point]) -> list[Point]:
        """Rows with the same label (a row per product of each day) as one point, summed (aggregate=max|mean): said
        (C107). Rows without a label are never combined."""
        how = self.aggregate()
        groups: dict[str, list[Point]] = {}
        order: list[str | Point] = []
        for p in points:
            if not p.label:
                order.append(p)
                continue
            if p.label not in groups:
                groups[p.label] = []
                order.append(p.label)
            groups[p.label].append(p)
        if all(len(g) == 1 for g in groups.values()):
            return points
        out = []
        for key in order:
            if isinstance(key, Point):
                out.append(key)
                continue
            g = groups[key]
            out.append(Point(key, [fold([p.values[i] for p in g], how) for i in range(len(self.names))], g[0].line,
                             rows=tuple(i for p in g for i in p.rows)))  # fmt: skip
        self.n.add("C107", f"{len(points)} rows {AGGREGATES[how]} into {len(out)} labels (repeated labels)",
                   self.t.line, "aggregate=max or aggregate=mean combines them otherwise")  # fmt: skip
        return out

    def place(self, points: list[Point]) -> bool:
        """x of each point: by real time between the labels when every one is a date (line, area, sparkline), else
        one after the other. Dates going back are said (C104) and drawn as written, evenly."""
        for i, p in enumerate(points):
            p.x = float(i)
        loc = getattr(self.lay.locale, "locale", None)
        days = parse_dates([p.label for p in points], loc)
        if days is None:
            return False
        back = next((i for i in range(1, len(days)) if days[i] < days[i - 1]), None)
        if back is not None:
            self.n.add("C104", f"dates out of order: '{points[back].label}' after '{points[back - 1].label}': drawn "
                       "in the order written, evenly spaced", points[back].line,
                       "sort the rows by date to space the points by time")  # fmt: skip
            return False
        if self.kind != "bar":
            for p, d in zip(points, days, strict=True):
                p.x = float((d - days[0]).days)
        return True

    # ------------------------------------------------------------------ size and labels
    def font(self) -> tuple[Font, bool]:
        """The labels' font: the printer font's look and size (Spleen at its line height) unless font= or size=."""
        kv, cell = self.a.kv, self.lay.p.cell[1]
        given = "font" in kv or "size" in kv
        fam = self.lay.family(kv.get("font") or "native")
        px = rasterfont.px_for(kv["size"], self.lay.p, cell, self.n, self.at("size=")) if "size" in kv else cell
        if fam.lower() == "native":
            fam = "Spleen" if px % cell == 0 else "Terminus"
        at = self.at("font=" if "font" in kv else "size=")
        return Font(self.lay.font_path(fam, False, px, at), px, f"{fam} {px}px"), given

    def small(self) -> Font:
        return Font(self.lay.font_path("Terminus", False, 12, self.t.line), 12, "Terminus 12px")

    def size(self) -> tuple[int, int, bool]:
        """(width, height, turned) of the drawing as it is read: width= (an object's: full, half, 50%, 30mm) and
        height= (mm, px, dots; default the width x 0.6, a sparkline one text line); orientation=vertical: width=
        across the paper, length= along it (the drawing's width as read)."""
        lay, kv = self.lay, self.a.kv
        room = lay.W - self.indent * lay.p.cell[0]
        w = lay.object_width(kv.get("width"), self.at("width=")) if "width" in kv else None
        if w is not None and w > room:
            lay.n.add("M101", f"width={kv['width']}: wider than the room here, {room} dots used", self.at("width="))
            w = room
        across = w or room
        orient = str(kv.get("orientation", "horizontal"))
        if orient not in ("horizontal", "vertical", "auto"):
            lay.n.add("M101", f"orientation={orient}", self.at("orientation="), "horizontal (the default) or vertical")
            orient = "horizontal"
        if orient == "vertical" and self.indent:
            lay.n.add("M101", "orientation=vertical: only a chart outside quotes and lists turns",
                      self.at("orientation="), "move it out of the quote or list")  # fmt: skip
            orient = "horizontal"
        tall = lay.attr_dots(self.a, "height", self.at("height="), lay.p.mm_to_dots(300))
        if orient == "vertical":
            if tall is not None:
                lay.n.add("M101", "height= does nothing on a turned chart: width= is across the paper, length= along",
                          self.at("height="), "length=80mm")  # fmt: skip
            length = lay.label_length(self.a, self.at("length=")) if "length" in kv else None
            return length or round(across / RATIO), across, True
        if "length" in kv:
            lay.n.add("M101", f"length={kv['length']} does nothing on a chart across the paper", self.at("length="),
                      "orientation=vertical turns it along the roll; height= sets its height")  # fmt: skip
        if tall is None:
            tall = lay.p.cell[1] if self.kind == "sparkline" else round(across * RATIO)
        return across, max(4, tall), False

    def y_ticks(self) -> int:
        n = count(self.lay, self.t, "y-ticks", 0, 12)
        return 3 if n is None else n

    def turned_labels(self) -> bool:
        given = str(self.a.kv.get("y-labels", "rotated"))
        if given not in ("rotated", "horizontal"):
            self.n.add("M101", f"y-labels={given}", self.at("y-labels="), "rotated (the default) or horizontal")
            return True
        return given == "rotated"

    def values(self, points: list[Point]) -> list[float]:
        return [v for p in points for v in p.values if v is not None]

    def geometry(self, font: Font, nticks: int, W: int, H: int, points: list[Point], wider: int = 0) -> Geo:
        vals = self.values(points)
        vmin, vmax = min(vals), max(vals)
        zero = self.kind in ("bar", "area") or vmin <= 0 or vmin <= (vmax - vmin)
        tv, lo, hi = ticks(vmin, vmax, nticks if self.axes else 0, zero, wider)
        if self.kind == "sparkline":
            lo, hi = (vmin, vmax) if vmax > vmin else (vmin - 1, vmax + 1)
        title_h = len(self.title_lines(font, W)) * font.h + GAP if self.title() else 0
        legend = self.legend_rows(font, W) if len(self.names) > 1 and self.kind != "sparkline" else []
        legend_h = len(legend) * (font.h + 2) + (GAP if legend else 0)
        x_h = font.h + GAP if self.axes and any(p.label for p in points) and self.x_mode() != 0 else 0
        top = title_h + STROKE
        bottom = H - legend_h - x_h - STROKE  # the X axis' top dot
        if self.axes:
            texts = [short(v, self.decimal) for v in tv]
            widest = max([0, *(font.width(s) for s in texts)])
            gutter = (font.h + GAP if self.turned else widest + TICK + GAP) if tv else 0
            left = gutter
            plot = (left + STROKE + 3, top, W - 1 - STROKE, bottom - 1)
        else:
            left, texts = 0, []
            plot = (STROKE, top, W - 1 - STROKE, bottom)  # a stroke's square reaches a dot right and down
        ok = plot[3] - plot[1] >= (MIN_PLOT if self.kind != "sparkline" else 2) and plot[2] - plot[0] >= MIN_PLOT
        if ok and tv:
            spans = self.y_label_spans(font, texts, tv, lo, hi, plot)
            ok = all(b[0] >= a[1] + (2 * GAP if self.turned else 2) for a, b in zip(spans, spans[1:], strict=False))
        return Geo(font, nticks, tv, lo, hi, left, plot, ok, title_h, legend_h, legend)

    def y(self, g: Geo, v: float) -> float:
        x0, y0, x1, y1 = g.plot
        return y1 - (v - g.lo) / (g.hi - g.lo) * (y1 - y0)

    def y_label_spans(self, font: Font, texts: list[str], tv: list[float], lo: float, hi: float, plot) -> list:
        """(top, bottom) of each Y label, bottom first, centred on its tick and kept between the plot's ends."""
        g = Geo(font, len(tv), tv, lo, hi, 0, plot, True)
        out = []
        for s, v in sorted(zip(texts, tv, strict=True), key=lambda p: -p[1]):
            size = font.width(s) if self.turned else font.h
            c = self.y(g, v)
            top = round(c - size / 2)
            top = max(0, min(top, plot[3] + STROKE - size)) if self.turned else max(0, top)
            out.append((top, top + size))
        return sorted(out)

    def title(self) -> str:
        return self.lay.text(str(self.a.kv["title"])).strip() if "title" in self.a.kv else ""

    def title_lines(self, font: Font, W: int, say: bool = False) -> list[str]:
        """The title wrapped at its spaces to the chart's width; a word wider than the chart cut with … (C105)."""
        lines: list[str] = []
        for word in self.title().split():
            word = self.shorten(font, word, W, "a word of the title", say)
            if lines and font.width(f"{lines[-1]} {word}") <= W:
                lines[-1] += f" {word}"
            else:
                lines.append(word)
        return lines

    def shorten(self, font: Font, text: str, width: int, what: str, say: bool) -> str:
        """text, or as much of it as fits `width` and …; said (C105) when cut and `say`."""
        if font.width(text) <= width:
            return text
        cut = text
        while cut and font.width(cut + "…") > width:
            cut = cut[:-1]
        if say:
            self.n.add("C105", f"{what} is wider than the chart: '{text[:30]}' printed as '{cut}…'", self.t.line,
                       "a shorter text, a smaller size= or a wider chart")  # fmt: skip
        return cut + "…"

    def x_mode(self):
        """x-labels=: 'all', 'ends', a number (0: none) or None (as many as fit)."""
        given = self.a.kv.get("x-labels")
        if given is None:
            return None
        g = str(given).strip()
        if g in ("all", "ends"):
            return g
        if g.isdigit():
            return int(g)
        if not getattr(self, "_said_x", False):
            self._said_x = True
            self.n.add("M101", f"x-labels={given}", self.at("x-labels="), "all, ends or a number (4: about 4)")
        return None

    def legend_rows(self, font: Font, W: int) -> list:
        """The legend's items in rows that fit W: [(width, [(x, i), …]), …]."""
        rows, cur, x = [], [], 0
        for i, name in enumerate(self.names):
            name = self.shorten(font, name or f"#{i + 1}", W - self.swatch_w() - GAP, "a series name", False)
            w = self.swatch_w() + GAP + font.width(name)
            if cur and x + 12 + w > W:
                rows.append((x, cur))
                cur, x = [], 0
            if cur:
                x += 12
            cur.append((x, i))
            x += w
        if cur:
            rows.append((x, cur))
        return rows

    def swatch_w(self) -> int:
        return 12 if self.kind == "bar" else 20

    # ------------------------------------------------------------------ drawing
    def draw(self, points: list[Point]) -> list | None:
        W, H, turned = self.size()
        self.turned = self.turned_labels()
        font, given = self.font()
        nt = self.y_ticks()
        points = self.thin(points, self.geometry(font, nt, W, H, points))
        fonts = [font, *([self.small()] if not given and font.px > 12 else [])]
        counts = [nt, *([2] if nt > 2 else [])]
        options = [(f, k, w) for f in fonts for k in counts for w in (0, 1, 2)] + [(fonts[-1], 0, 0)]
        mode = self.x_mode()
        ends = min(2, len(points), *([mode] if isinstance(mode, int) else []))  # labels each try must fit
        ends = ends if self.axes and any(p.label for p in points) else 0
        g = next((g for f, k, w in options if (g := self.geometry(f, k, W, H, points, w)).ok
                  and len(self.x_picks(points, self.xs(points, g), g, say=False)) >= ends), None)  # fmt: skip
        if g is None:
            g = self.geometry(*options[-1][:2], W, H, points)
        if g.plot[3] - g.plot[1] < STROKE or g.plot[2] - g.plot[0] < STROKE:
            self.n.add("C105", f"a chart {H} dots tall and {W} wide has no room to draw beside its labels: printed "
                       "as a table", self.t.line, "a taller height= (height=30mm) or a wider width=")  # fmt: skip
            return None
        if self.axes and (g.font is not font or g.nticks != nt):
            what = []
            if g.nticks != nt:
                what.append(f"{g.nticks} values on the Y axis" if g.nticks else "no values on the Y axis")
            if g.font is not font:
                what.append(f"labels in {g.font.name}")
            self.n.add("C105", f"a chart {H} dots tall and {W} wide is too small for its labels: {', '.join(what)}",
                       self.t.line, "a taller height= (height=30mm) or a smaller size= (size=16px)")  # fmt: skip
        im = Image.new("1", (W, H), 1)
        d = ImageDraw.Draw(im)
        self.drawn = (H, W) if turned else (W, H)  # as it lies on the paper: across, along
        xs = self.xs(points, g)
        if self.a.has("grid") and self.axes:
            for v in g.tick_values:
                yy = round(self.y(g, v))
                if yy < g.plot[3] - 2:
                    for x in range(g.plot[0], g.plot[2], 6):
                        d.rectangle((x, yy, x + 1, yy + 1), fill=0)
        if self.kind == "bar":
            self.bars(im, d, points, g)
        else:
            if self.kind == "area":
                self.fill(im, points, xs, g)
                if g.lo < 0 < g.hi:  # where zero is: the fill reaches up or down to it
                    zy = round(self.y(g, 0.0))
                    d.rectangle((g.plot[0], zy, g.plot[2], zy + STROKE - 1), fill=0)
            for i in range(len(self.names)):
                self.line_series(d, [(x, p.values[i]) for x, p in zip(xs, points, strict=True)], g, DASHES[i % 4])
        if self.axes:
            self.axes_and_labels(im, d, points, xs, g)
        self.texts(im, d, g, W)
        self.summary(points, g, turned)
        return [self.row(im, turned)]

    def thin(self, points: list[Point], g: Geo) -> list[Point]:
        """More points than the drawing has room for (2 dots each; a bar group 2 dots a bar and 2 between): runs of
        neighbours as one point, their mean (aggregate=max: their largest), said (C102)."""
        room = max(1, g.plot[2] - g.plot[0])
        each = 2 * len(self.names) + 2 if self.kind == "bar" else 2
        fits = max(1, room // each)
        if len(points) <= fits:
            return points
        k = math.ceil(len(points) / fits)
        how = "max" if self.a.kv.get("aggregate") == "max" else "mean"
        out = []
        for s in range(0, len(points), k):
            run = points[s : s + k]
            label = run[-1].label if s + k >= len(points) else run[0].label
            out.append(Point(label, [fold([p.values[i] for p in run], how) for i in range(len(self.names))],
                             run[0].line, sum(p.x for p in run) / len(run)))  # fmt: skip
        word = "the largest kept" if how == "max" else "averaged"
        self.n.add("C102", f"{len(points)} points on a drawing {room} dots wide: every {k} points {word} into one "
                   f"({len(out)} drawn)", self.t.line,
                   "aggregate=max keeps the peaks; last=N draws only the last N; a wider chart shows more")  # fmt: skip
        return out

    def xs(self, points: list[Point], g: Geo) -> list[float]:
        x0, _, x1, _ = g.plot
        if self.kind == "bar":
            slot = (x1 - x0) / len(points)
            return [x0 + slot * (i + 0.5) for i in range(len(points))]
        lo, hi = points[0].x, points[-1].x
        if hi <= lo:
            return [(x0 + x1) / 2] * len(points) if len(points) == 1 else [
                x0 + (x1 - x0) * i / (len(points) - 1) for i in range(len(points))]  # fmt: skip
        return [x0 + (x1 - x0) * (p.x - lo) / (hi - lo) for p in points]

    def line_series(self, d: ImageDraw.ImageDraw, pts: list[tuple[float, float | None]], g: Geo, dash) -> None:
        run: list[tuple[float, float]] = []
        for x, v in [*pts, (0.0, None)]:
            if v is None:
                if len(run) == 1:
                    x0, y0 = run[0]
                    d.rectangle((round(x0) - 1, round(y0) - 1, round(x0) + 1, round(y0) + 1), fill=0)
                elif run:
                    polyline(d, run, dash)
                run = []
            else:
                run.append((x, self.y(g, v)))

    def fill(self, im: Image.Image, points: list[Point], xs: list[float], g: Geo) -> None:
        """Under each series down to zero (up to zero for negative values), in the paper's tested grey pattern."""
        base = min(max(self.y(g, 0.0), g.plot[1]), g.plot[3] + 1)
        mask = Image.new("1", im.size, 0)
        md = ImageDraw.Draw(mask)
        for i in range(len(self.names)):
            run: list[tuple[float, float]] = []
            for x, p in [*zip(xs, points, strict=True), (0.0, None)]:
                v = p.values[i] if p is not None else None
                if v is None:
                    if len(run) > 1:
                        md.polygon([*run, (run[-1][0], base), (run[0][0], base)], fill=1)
                    run = []
                else:
                    run.append((x, self.y(g, v)))
        pattern(im, mask)

    def bars(self, im: Image.Image, d: ImageDraw.ImageDraw, points: list[Point], g: Geo) -> None:
        x0, _, x1, _ = g.plot
        ns = len(self.names)
        slot = (x1 - x0) / len(points)
        inner = max(2 * ns, slot - max(2, round(slot * 0.25)))
        bw = max(2, int(inner // ns))
        base = min(max(round(self.y(g, 0.0)), g.plot[1]), g.plot[3] + 1)
        for i, p in enumerate(points):
            left = round(x0 + slot * i + (slot - bw * ns) / 2)
            for s, v in enumerate(p.values):
                if v is None:
                    continue
                top = round(self.y(g, v))
                a, b = sorted((top, base))
                if b - a < STROKE:
                    a, b = (b - STROKE, b) if v >= 0 else (a, a + STROKE)
                bar(im, d, (left + s * bw, a, left + (s + 1) * bw - 1 - (1 if ns > 1 and bw > 4 else 0), b), s)
        if g.lo < 0 < g.hi:
            d.rectangle((x0, base, x1, base + STROKE - 1), fill=0)

    def axes_and_labels(self, im: Image.Image, d: ImageDraw.ImageDraw, points, xs, g: Geo) -> None:
        f = g.font
        x0, y0, x1, y1 = g.plot
        axis = y1 + 1
        self.axis_y = axis
        d.rectangle((g.left, y0 - STROKE, g.left + STROKE - 1, axis + STROKE - 1), fill=0)
        d.rectangle((g.left, axis, x1 + STROKE, axis + STROKE - 1), fill=0)
        texts = [short(v, self.decimal) for v in g.tick_values]
        for s, v in zip(texts, g.tick_values, strict=True):
            c = self.y(g, v)
            d.rectangle((g.left - TICK, round(c) - 1, g.left - 1, round(c)), fill=0)
            pic = f.image(s)
            if self.turned:
                pic = pic.rotate(90, expand=True)
                top = max(0, min(round(c - pic.height / 2), axis + STROKE - pic.height))
                im.paste(pic, (0, top))
            else:
                top = max(0, round(c - f.h / 2))
                im.paste(pic, (g.left - TICK - GAP - pic.width, top))
            self.labels_drawn.append(Label(s, (0 if self.turned else g.left - TICK - GAP - pic.width, top, pic.width,
                                               pic.height), self.turned))  # fmt: skip
        for i in self.x_picks(points, xs, g):
            s = self.shorten(f, points[i].label, im.width, "an X label", True)
            w = f.width(s)
            left = max(0, min(round(xs[i] - w / 2), im.width - w))
            d.rectangle((round(xs[i]) - 1, axis + STROKE, round(xs[i]), axis + STROKE + 2), fill=0)
            im.paste(f.image(s), (left, axis + STROKE + GAP - 2))
            self.labels_drawn.append(Label(s, (left, axis + STROKE + GAP - 2, w, f.h), kind="x"))

    def x_picks(self, points: list[Point], xs: list[float], g: Geo, say: bool = True) -> list[int]:
        """Which X labels print: x-labels=all, ends, N, or as many as fit without touching (the first and the last
        always among them). What was asked and does not fit is said (C105)."""
        n, f = len(points), g.font
        if not any(p.label for p in points) or not self.axes:
            return []
        W = round(g.plot[2] + STROKE + 1)

        def fits(idx: list[int]) -> bool:
            right = -GAP * 2
            for i in idx:
                w = f.width(self.shorten(f, points[i].label, W, "", False))
                left = max(0, min(round(xs[i] - w / 2), W - w))
                if left < right + GAP * 2:
                    return False
                right = left + w
            return True

        def spread(k: int) -> list[int]:
            return [0] if k <= 1 or n == 1 else sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})

        mode = self.x_mode()
        if mode == 0:
            return []
        want = {"all": n, "ends": min(2, n)}.get(mode, mode) if mode is not None else n
        for k in range(min(want, n), 0, -1):
            idx = list(range(n)) if k == n else spread(k)
            if fits(idx):
                if say and mode is not None and k < min(want, n):
                    self.n.add("C105", f"x-labels={mode}: {min(want, n)} labels do not fit side by side: {k} printed",
                               self.at("x-labels="), "a smaller size=, shorter labels or a wider chart")  # fmt: skip
                return idx
        return []

    def texts(self, im: Image.Image, d: ImageDraw.ImageDraw, g: Geo, W: int) -> None:
        f = g.font
        for k, line in enumerate(self.title_lines(f, W, say=True)):
            w = f.width(line)
            left = max(0, (W - w) // 2)
            im.paste(f.image(line), (left, k * f.h))
            self.labels_drawn.append(Label(line, (left, k * f.h, w, f.h), kind="title"))
        y = im.height - g.legend_h + GAP
        for rank, (width, items) in enumerate(g.legend):
            start = max(0, (W - width) // 2)
            for x, i in items:
                x += start
                sw = self.swatch_w()
                mid = y + f.h // 2
                if self.kind == "bar":
                    bar(im, d, (x, mid - 6, x + sw - 1, mid + 5), i)
                else:
                    polyline(d, [(x, mid), (x + sw - 1, mid)], DASHES[i % 4])
                name = self.shorten(f, self.names[i] or f"#{i + 1}", W - sw - GAP, "a series name", True)
                im.paste(f.image(name), (x + sw + GAP, y))
                self.labels_drawn.append(Label(name, (x + sw + GAP, y, f.width(name), f.h), kind="legend", rank=rank))
            y += f.h + 2

    def summary(self, points: list[Point], g: Geo, turned: bool) -> None:
        """C101 (bobina check only): what was drawn, how the values were read, its size and place."""
        first = [p.values[0] for p in points if p.values[0] is not None]
        read = " · ".join(f"{v:.15g}" for v in first[:6]) + (" …" if len(first) > 6 else "")
        x = "by date" if self.dates and self.kind != "bar" else "evenly spaced"
        ends = f" ({points[0].label} … {points[-1].label})" if points[0].label else ""
        y = " · ".join(short(v, self.decimal) for v in g.tick_values) or "none"
        if g.tick_values:
            y += " (turned along the axis)" if self.turned else " (upright)"
        series = ", ".join(n or "(untitled)" for n in self.names)
        wide, tall = self.drawn
        extras = [x for x, on in (("a grid", self.a.has("grid")), ("no axes", self.a.has("no-axes")),
                                  ("turned along the roll", turned)) if on]  # fmt: skip
        place = {"center": "centred", "left": "on the left", "right": "on the right"}[self.lay.object_align(self.a)]
        room = self.lay.W - self.indent * self.lay.p.cell[0]
        place = "the full width" if wide >= room else place
        self.n.add("C101", f"chart={self.kind}: {len(points)} points, {len(self.names)} series ({series}); x "
                   f"{x}{ends}; y ticks {y}; values read: {read}; {wide}x{tall} dots, {place}"
                   + "".join(f", {e}" for e in extras), self.t.line)  # fmt: skip

    def row(self, im: Image.Image, turned: bool) -> BitmapRow:
        lay = self.lay
        align = lay.object_align(self.a)
        if turned:
            im = im.rotate(-90, expand=True)  # clockwise, like a turned table: the chart's top on the paper's right
        cw = lay.p.cell[0]
        room = lay.W - self.indent * cw
        inner = imaging.place(im, room, align)
        placed = Image.new("1", (lay.W, im.height), 1)
        placed.paste(inner, (lay.W - room, 0))
        if self.indent:
            placed = lay.draw_bars(placed, self.indent, 0)
        shift = lay.W - room + {"left": 0, "right": room - im.width}.get(align, (room - im.width) // 2)
        view = None if turned else self.view(placed, max(0, shift))
        return BitmapRow(placed, self.t.line, "chart", untested=("charts",), view=view)

    def view(self, placed: Image.Image, shift: int) -> list[str]:
        """The terminal's lines: the drawing in braille, its labels as text where they are."""
        from .view import braille

        cw, chh = self.lay.p.cell
        plot = placed.copy()
        d = ImageDraw.Draw(plot)
        for lab in self.labels_drawn:
            x, y, w, h = lab.box
            d.rectangle((x + shift, y, x + shift + w - 1, y + h - 1), fill=1)
        lines = braille(thicken(plot), (cw, chh))
        taken: dict[int, list[tuple[int, int]]] = {}  # a label in a smaller font needs more letters: none overlaps
        below = getattr(self, "axis_y", -chh) // chh + 1  # the first line under the X axis
        xrow = max([below, *((lab.box[1] + lab.box[3] // 2) // chh for lab in self.labels_drawn if lab.kind == "x")])
        has_x = any(lab.kind == "x" for lab in self.labels_drawn)
        for lab in self.labels_drawn:
            x, y, w, h = lab.box
            row = max(0, (y + h // 2) // chh)
            if lab.kind == "x":
                row = xrow
            elif lab.kind == "legend":
                row = max(row, (xrow + 1 if has_x else below) + lab.rank)
            while row >= len(lines):
                lines.append(" " * len(lines[0]))
            s = lines[row]
            col = max(0, min((x + shift) // cw, len(s) - len(lab.text)))
            end = col + len(lab.text)
            if any(col <= b and a <= end for a, b in taken.get(row, [])):
                continue
            taken.setdefault(row, []).append((col, end))
            lines[row] = (s[:col] + lab.text + s[end:])[: len(s)]
        return lines


def thicken(im: Image.Image) -> Image.Image:
    """The image (mode L) with every dot a dot wider and taller, for the braille view: a 2-dot line across two of its
    cells stays seen. Nothing wraps around from one edge to the other."""
    g = im.convert("L")
    for dx, dy in ((1, 0), (0, 1)):
        moved = Image.new("L", g.size, 255)
        moved.paste(g, (dx, dy))
        g = ImageChops.darker(g, moved)
    return g


def machine_number(text: str) -> float | None:
    """A number as a program writes it (JSON, a spreadsheet's numeric cell): 1234.5, -0.25, 1e6; None otherwise."""
    if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", text):
        return None
    return float(text)


def fold(values: list[float | None], how: str) -> float | None:
    got = [v for v in values if v is not None]
    if not got:
        return None
    return max(got) if how == "max" else sum(got) / len(got) if how == "mean" else sum(got)


def polyline(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], dash: tuple = ()) -> None:
    """A STROKE-dot line through pts, solid or in a dash pattern (on, off, …) that runs on across the corners."""
    if not dash:
        for a, b in zip(pts, pts[1:], strict=False):
            segment(d, a, b)
        return
    period = list(dash)
    k, left = 0, float(period[0])
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        seg = math.hypot(bx - ax, by - ay)
        at = 0.0
        while at < seg:
            step = min(left, seg - at)
            if k % 2 == 0 and step > 0:
                p0 = (ax + (bx - ax) * at / seg, ay + (by - ay) * at / seg)
                p1 = (ax + (bx - ax) * (at + step) / seg, ay + (by - ay) * (at + step) / seg)
                segment(d, p0, p1)
            at += step
            left -= step
            if left <= 1e-9:
                k = (k + 1) % len(period)
                left = float(period[k])


def segment(d: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float]) -> None:
    """A line from a to b drawn by a STROKE x STROKE square: at least STROKE dots thick across it, whatever its slope
    (a line PIL draws width=2 is 1 dot thick where it is shallow, and prints broken)."""
    (ax, ay), (bx, by) = (round(a[0]), round(a[1])), (round(b[0]), round(b[1]))
    for dx in range(STROKE):
        for dy in range(STROKE):
            d.line([(ax + dx, ay + dy), (bx + dx, by + dy)], fill=0, width=1)


def pattern(im: Image.Image, mask: Image.Image) -> None:
    """The tested light grey (imaging.SHADE_DOT squares every SHADE_STEP dots, every other one left out) where mask
    is set, anchored to the image as a table's .shade is."""
    box = mask.getbbox()
    if not box:
        return
    step, dot = imaging.SHADE_STEP, imaging.SHADE_DOT
    m = mask.load()
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    for y in range(y0 - y0 % step, y1, step):
        for x in range(x0 - x0 % step, x1, step):
            if (x // step + y // step) % 2:
                continue
            if all(0 <= a < im.width and 0 <= b < im.height and m[a, b] for a in (x, x + dot - 1)
                   for b in (y, y + dot - 1)):  # fmt: skip
                d.rectangle((x, y, x + dot - 1, y + dot - 1), fill=0)


def bar(im: Image.Image, d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], series: int) -> None:
    """A bar of series 0 (black), 1 (a frame and the tested grey inside), 2 (a frame), then again."""
    x0, y0, x1, y1 = box
    style = series % 3
    if style == 0 or min(x1 - x0, y1 - y0) < 2 * STROKE + 2:  # too small for a frame around anything: black
        d.rectangle(box, fill=0)
        return
    d.rectangle(box, fill=1, outline=0, width=STROKE)  # white inside: no grid line through it
    if style == 1:
        mask = Image.new("1", im.size, 0)
        ImageDraw.Draw(mask).rectangle((x0 + STROKE + 1, y0 + STROKE + 1, x1 - STROKE - 1, y1 - STROKE - 1), fill=1)
        pattern(im, mask)
