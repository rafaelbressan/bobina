"""Charts drawn from a table ({chart=line|bar|area|sparkline} under it) and tables whose rows come from a file
(data=FILE): how the values are read, combined and spaced, what the drawing looks like on the dots, and that a file's
cells stay data."""

import pytest

from bobina import charts, view
from bobina.engine import build
from bobina.nudges import SecurityError
from bobina.rows import BitmapRow, RawRow, TextRow
from bobina.templating import Tainted

SUPPLY = """| day | supply |
|---|--:|
| Jan 27 | 0 |
| Feb 15 | 800 |
| Apr 1 | 3500 |
| Jun 1 | 52000 |
| Jul 1 | 120000 |
| Sep 1 | 300000 |
| Oct 1 | 410000 |
| Nov 17 | 749069 |
"""


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in [*res.nudges, *res.nudges.check_only] if n.code == code]


def chart_rows(res) -> list[BitmapRow]:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "chart"]


def chart(res):
    (row,) = chart_rows(res)
    return row.image


def ink(im, box=None) -> int:
    im = im.crop(box) if box else im
    return im.convert("L").histogram()[0]


def peak_x(im) -> int:
    """x of the topmost black dot (a chart without axes: the highest point of its line)."""
    px = im.load()
    for y in range(im.height):
        xs = [x for x in range(im.width) if px[x, y] == 0]
        if xs:
            return sum(xs) // len(xs)
    raise AssertionError("no ink")


def text_lines(res) -> list[str]:
    return ["".join(c.ch for c in r.cells).rstrip() for r in res.rows if isinstance(r, TextRow)]


# ---------------------------------------------------------------------------------------------------- reading


def test_a_table_with_chart_prints_a_chart_instead_of_the_table():
    res = build(SUPPLY + "{chart=line height=30mm}\n")
    assert len(chart_rows(res)) == 1 and not text_lines(res)
    assert chart(res).height == 240  # 30 mm at 203 dpi
    assert not [c for c in codes(res) if c.startswith("M")]  # chart= and height= are known on a table's line
    (summary,) = said(res, "C101")
    assert "8 points" in summary and "by date" in summary and "0 · 800 · 3500" in summary


def test_numbers_are_read_in_the_documents_locale():
    src = "---\nlocale: pt-BR\n---\n| dia | vendas |\n|---|--:|\n| Seg | R$ 1.240,50 |\n| Ter | 980 |\n{chart=bar}\n"
    (summary,) = said(build(src), "C101")
    assert "values read: 1240.5 · 980" in summary
    en = "| day | sales |\n|---|--:|\n| Mon | $1,240.50 |\n| Tue | 2.5 |\n{chart=bar}\n"
    assert "values read: 1240.5 · 2.5" in said(build(en), "C101")[0]


def test_a_value_that_is_not_a_number_leaves_its_row_out():
    src = "| day | n |\n|---|--:|\n| a | 1 |\n| b | lots |\n| c | 3 |\n{chart=line}\n"
    res = build(src)
    (msg,) = said(res, "C103")
    assert "'lots'" in msg and "'b'" in msg
    assert [n.line for n in res.nudges if n.code == "C103"] == [4]
    assert "2 points" in said(res, "C101")[0]
    gap = "| day | n |\n|---|--:|\n| a | 1 |\n| b | |\n| c | 3 |\n{chart=line}\n"
    assert "C103" not in codes(build(gap))  # an empty cell is a gap, not a mistake


def test_repeated_labels_are_summed_and_aggregate_says_how():
    rows = "".join(f"| d{i % 5} | {i} |\n" for i in range(12))
    res = build(f"| day | n |\n|---|--:|\n{rows}{{chart=bar}}\n")
    assert said(res, "C107") == ["12 rows summed into 5 labels (repeated labels)"]
    assert "values read: 15 · 18 · 9 · 11 · 13" in said(res, "C101")[0]  # d0: 0+5+10, d1: 1+6+11, d2: 2+7 …
    res = build(f"| day | n |\n|---|--:|\n{rows}{{chart=bar aggregate=max}}\n")
    assert "values read: 10 · 11 · 7 · 8 · 9" in said(res, "C101")[0]
    assert "M101" in codes(build(f"| day | n |\n|---|--:|\n{rows}{{chart=bar aggregate=median}}\n"))


def test_last_keeps_the_last_points_after_combining():
    rows = "".join(f"| d{i % 5} | {i} |\n" for i in range(12))
    res = build(f"| day | n |\n|---|--:|\n{rows}{{chart=bar last=2}}\n")
    assert "2 points" in said(res, "C101")[0] and "(d3 … d4)" in said(res, "C101")[0]


def test_dates_space_the_points_by_time_other_labels_evenly():
    def peak(labels: tuple[str, str, str]) -> int:
        a, b, c = labels
        src = f"| d | n |\n|---|--:|\n| {a} | 0 |\n| {b} | 10 |\n| {c} | 0 |\n{{chart=line .no-axes}}\n"
        return peak_x(chart(build(src)))

    assert peak(("Jan 1", "Jan 2", "Jan 31")) < 40  # one day of thirty: near the left
    assert peak(("2026-01-01", "2026-01-30", "2026-01-31")) > 340  # 29 of 30 days: near the right
    assert abs(peak(("a", "b", "c")) - 192) < 10  # not dates: the middle
    pt = "---\nlocale: pt-BR\n---\n"
    assert peak_x(chart(build(pt + "| d | n |\n|---|--:|\n| 1 fev | 0 |\n| 2 fev | 10 |\n| 1 mar | 0 |\n"
                              "{chart=line .no-axes}\n"))) < 40  # fmt: skip


def test_parse_dates_reads_the_usual_forms():
    from babel import Locale

    days = charts.parse_dates(["27/01", "27/01/2026", "2026-11-07", "Nov 17", "17 nov"], Locale.parse("pt_BR"))
    assert days is not None and [(d.month, d.day) for d in days] == [(1, 27), (1, 27), (11, 7), (11, 17), (11, 17)]
    assert charts.parse_dates(["Dec 20", "Jan 5"], None)[1].year == 2001  # into the next year, not back
    assert charts.parse_dates(["00h", "03h"], None) is None
    assert charts.parse_dates(["Seg", "Ter"], Locale.parse("pt_BR")) is None


def test_dates_out_of_order_are_drawn_as_written():
    src = "| d | n |\n|---|--:|\n| Mar 1 | 0 |\n| Feb 1 | 10 |\n| Apr 1 | 0 |\n{chart=line .no-axes}\n"
    res = build(src)
    assert said(res, "C104") and "'Feb 1' after 'Mar 1'" in said(res, "C104")[0]
    assert abs(peak_x(chart(res)) - 192) < 10  # evenly spaced, in the order written


def test_more_points_than_the_width_shows_are_averaged():
    rows = "".join(f"| {i} | {i % 7} |\n" for i in range(600))
    res = build(f"| x | n |\n|---|--:|\n{rows}{{chart=line}}\n")
    (msg,) = said(res, "C102")
    assert msg.startswith("600 points") and "averaged" in msg
    assert "the largest kept" in said(build(f"| x | n |\n|---|--:|\n{rows}{{chart=line aggregate=max}}\n"), "C102")[0]


# ---------------------------------------------------------------------------------------------------- drawing


def axis_x(im) -> int:
    """The Y axis: the column with the longest run of ink."""
    px = im.load()
    best, at = 0, 0
    for x in range(im.width // 2):
        run = longest = 0
        for y in range(im.height):
            run = run + 1 if px[x, y] == 0 else 0
            longest = max(longest, run)
        if longest > best:
            best, at = longest, x
    return at


def test_y_labels_are_turned_along_the_axis_by_default():
    turned = chart(build(SUPPLY + "{chart=line}\n"))
    upright = chart(build(SUPPLY + "{chart=line y-labels=horizontal}\n"))
    a, b = axis_x(turned), axis_x(upright)
    assert a < 32 < b  # turned: one text line of width; upright: "500K" and a tick
    box = turned.crop((0, 0, a - 3, turned.height - 30)).point(lambda v: 255 - v).getbbox()
    assert box[3] - box[1] > 2 * (box[2] - box[0])  # the labels run up the axis
    assert "M101" in codes(build(SUPPLY + "{chart=line y-labels=sideways}\n"))


def test_a_sparkline_is_one_text_line_tall_without_axes():
    src = "| | |\n|---|--:|\n| | 1 |\n| | 5 |\n| | 3 |\n{chart=sparkline}\n"
    res = build(src)
    im = chart(res)
    assert im.height == 24 and not res.nudges.check_only[0].message.count("ticks 0")
    assert ink(im, (0, 0, 1, 24)) == 0  # no axis at the left edge: only the line
    assert chart(build(src.replace("sparkline", "sparkline height=10mm"))).height == 80


def test_area_fills_down_to_zero_and_up_to_it_for_negatives():
    neg = "| x | t |\n|---|--:|\n| a | -1 |\n| b | -1 |\n| c | -1 |\n{chart=KIND .no-axes height=100}\n"
    area, line = chart(build(neg.replace("KIND", "area"))), chart(build(neg.replace("KIND", "line")))
    mid = (0, 40, area.width, 60)  # between zero (the top) and the line (the bottom)
    assert ink(line, mid) == 0 and 0 < ink(area, mid) < area.width * 20 // 4  # the grey pattern, not black
    pos = neg.replace("-1", "4")
    assert ink(chart(build(pos.replace("KIND", "area"))), mid) > 0  # under a positive line, down to zero


def test_with_table_prints_the_table_under_the_chart():
    res = build(SUPPLY + "{chart=line .with-table style=receipt}\n")
    kinds = [type(r).__name__ for r in res.rows if type(r).__name__ != "FeedRow"]
    assert kinds[0] == "BitmapRow" and chart_rows(res)
    assert any("Nov 17" in t and "749069" in t for t in text_lines(res))
    assert not [c for c in codes(res) if c == "M101"]  # height=, width= and the chart's keys are not the table's


def test_bars_have_a_legend_for_two_series():
    src = "| d | sales | goal |\n|---|--:|--:|\n| Mon | 5 | 4 |\n| Tue | 3 | 4 |\n{chart=bar}\n"
    res = build(src)
    lines = view.lines(res.rows, res.profile)
    assert any("sales" in ln and "goal" in ln for ln in lines)
    one = "| d | sales |\n|---|--:|\n| Mon | 5 |\n| Tue | 3 |\n{chart=bar}\n"
    assert not any("sales" in ln for ln in view.lines(build(one).rows, build(one).profile))


def test_the_view_shows_the_drawing_in_braille_and_the_labels_as_text():
    res = build(SUPPLY + "{chart=line}\n")
    out = "\n".join(view.lines(res.rows, res.profile))
    assert "Jan 27" in out and "Nov 17" in out and "500K" in out and "250K" in out
    assert any("⠀" < ch <= "⣿" for ch in out)


def test_a_chart_without_a_value_column_prints_the_table():
    res = build("| day |\n|---|\n| Mon |\n{chart=line}\n")
    assert "C106" in codes(res) and not chart_rows(res) and text_lines(res)


def test_an_unknown_chart_type_is_said_and_the_table_prints():
    res = build("| d | n |\n|---|--:|\n| a | 1 |\n{chart=pie}\n")
    assert any("chart=pie" in m for m in said(res, "M101")) and text_lines(res)
    assert chart_rows(build("| d | n |\n|---|--:|\n| a | 1 |\n| b | 2 |\n{chart=Line}\n"))  # said, and drawn


def test_a_charts_keys_without_chart_are_said():
    res = build("| d | n |\n|---|--:|\n| a | 1 |\n{y-ticks=3 .grid}\n")
    assert any("with chart= only" in m for m in said(res, "M101")) and text_lines(res)


def test_a_chart_too_short_for_its_labels_gets_fewer_or_smaller_ones():
    res = build(SUPPLY + "{chart=line height=12mm}\n")
    assert said(res, "C105") and chart(res).height == 96
    res = build(SUPPLY + "{chart=line x-labels=all}\n")
    assert any("x-labels=all" in m for m in said(res, "C105"))


def test_orientation_vertical_turns_the_chart_along_the_roll():
    res = build(SUPPLY + "{chart=line orientation=vertical length=80mm}\n")
    im = chart(res)
    assert im.width == 384 and im.height == 639 and chart_rows(res)[0].view is None


def test_a_chart_in_a_half_width_box_and_in_columns():
    box = build("::: {.box width=half}\n" + SUPPLY + "{chart=bar}\n:::\n")
    assert not [c for c in codes(box) if c.startswith(("M", "L"))]
    cols = build(":::: {.columns}\n::: {width=40%}\n**749K**\n:::\n::: {}\n| | |\n|---|--:|\n| | 1 |\n| | 4 |\n"
                 "{chart=sparkline}\n:::\n::::\n")  # fmt: skip
    assert not [c for c in codes(cols) if c.startswith(("M", "L"))]


# ---------------------------------------------------------------------------------------------------- files


CSV = """data,produto,valor,meta
2026-11-02,pão,320.50,400
2026-11-02,bolo,210.00,400
2026-11-03,pão,410.00,400
2026-11-04,pão,380.75,400
"""


def test_a_chart_from_a_file_picks_its_columns_by_title(tmp_path):
    (tmp_path / "vendas.csv").write_text(CSV, encoding="utf-8")
    res = build("| data | valor |\n|---|--:|\n{chart=bar data=vendas.csv}\n", base_dir=str(tmp_path))
    assert chart_rows(res) and said(res, "C107") == ["4 rows summed into 3 labels (repeated labels)"]
    assert "values read: 530.5 · 410 · 380.75" in said(res, "C101")[0]


def test_a_title_the_file_does_not_have_lists_its_columns(tmp_path):
    (tmp_path / "vendas.csv").write_text(CSV, encoding="utf-8")
    res = build("| data | total |\n|---|--:|\n{chart=bar data=vendas.csv}\n", base_dir=str(tmp_path))
    (msg,) = said(res, "C108")
    assert "'total'" in msg and "data, produto, valor, meta" in msg


def test_a_missing_file_is_said_and_the_rest_prints(tmp_path):
    res = build("| a | b |\n|---|--:|\n{chart=bar data=nope.csv}\n\nend\n", base_dir=str(tmp_path))
    assert said(res, "C109") and "end" in text_lines(res)


def test_a_file_without_chart_prints_as_a_table_with_its_styles(tmp_path):
    (tmp_path / "vendas.csv").write_text(CSV, encoding="utf-8")
    res = build("| data | produto | valor |\n|---|---|--:|\n{data=vendas.csv style=receipt last=2}\n",
                base_dir=str(tmp_path))  # fmt: skip
    lines = text_lines(res)
    assert lines[0].split() == ["data", "produto", "valor"]
    assert [ln.split() for ln in lines[1:]] == [["2026-11-03", "pão", "410.00"], ["2026-11-04", "pão", "380.75"]]
    assert not chart_rows(res) and not codes(res)


def test_a_files_cells_are_data_never_markup(tmp_path):
    (tmp_path / "a.png").write_bytes(b"")
    (tmp_path / "evil.csv").write_text(
        'name,value\n**x**,1\n![i](a.png),2\n```raw,3\n{{ x }},4\n"0 :heart:",5\n', encoding="utf-8"
    )
    res = build("| name | value |\n|---|--:|\n{data=evil.csv}\n", base_dir=str(tmp_path), fields={"x": "LEAK"})
    names = [ln.rsplit(" ", 1)[0].strip() for ln in text_lines(res)[1:]]
    assert names == ["**x**", "![i](a.png)", "```raw", "{{ x }}", "0 :heart:"]
    assert not [r for r in res.rows if isinstance(r, RawRow)]
    assert not [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]
    assert "LEAK" not in "".join(text_lines(res))


def test_a_data_path_through_templating(tmp_path):
    (tmp_path / "nov.csv").write_text(CSV, encoding="utf-8")
    src = "| data | valor |\n|---|--:|\n{chart=bar data={{ arquivo }}}\n"
    res = build(src, base_dir=str(tmp_path), fields={"arquivo": Tainted("nov.csv")})
    assert chart_rows(res) and not said(res, "C109")
    for bad in ("../secret.csv", str(tmp_path / "x.png"), "/etc/passwd"):
        with pytest.raises(SecurityError) as e:
            build(src, base_dir=str(tmp_path), fields={"arquivo": Tainted(bad)})
        assert e.value.nudge.code == "M312"


def test_under_sandbox_a_file_outside_the_allowed_folders_is_not_read(tmp_path):
    (tmp_path / "doc").mkdir()
    (tmp_path / "vendas.csv").write_text(CSV, encoding="utf-8")
    res = build("| data | valor |\n|---|--:|\n{data=../vendas.csv}\n", base_dir=str(tmp_path / "doc"),
                image_dirs=(str(tmp_path / "doc"),))  # fmt: skip
    assert said(res, "C109") and "sandbox" in said(res, "C109")[0]


# ---------------------------------------------------------------------------------------------------- numbers


@pytest.mark.parametrize(
    "value, text", [(300000, "300K"), (1_200_000, "1.2M"), (0.5, "0.5"), (-1.5, "-1.5"), (0, "0"), (2500, "2.5K")]
)
def test_tick_values_are_written_short(value, text):
    assert charts.short(value) == text


def test_ticks_are_round_and_cover_the_values():
    assert charts.ticks(0, 749069, 3, True)[0] == [0, 250000, 500000]
    assert charts.ticks(-1.5, 4.5, 3, True)[0] == [-2, 0, 2]
    t, lo, hi = charts.ticks(120, 210, 3, False)
    assert t == [120, 150, 180] and lo == 120 and hi == 210


def test_the_guides_examples_print_without_a_warning(tmp_path):
    from pathlib import Path

    guide = (Path(__file__).resolve().parents[1] / "docs" / "guides" / "charts.md").read_text(encoding="utf-8")
    csv = guide.split("```text\n", 1)[1].split("```", 1)[0]
    (tmp_path / "vendas.csv").write_text(csv, encoding="utf-8")
    blocks = guide.split("```markdown\n")[1:]
    assert len(blocks) == 3
    for block in blocks:
        res = build(block.split("```", 1)[0], base_dir=str(tmp_path))
        assert chart_rows(res) or any(r.columns for r in res.rows if isinstance(r, BitmapRow))
        assert not [n.code for n in res.nudges if n.severity in ("warning", "error")], block


# ---------------------------------------------------------------------------------------------------- review fixes


def runs(im, vertical: bool) -> list[int]:
    """The length of every run of black dots along each column (vertical) or each row."""
    px, out = im.load(), []
    outer, inner = (im.width, im.height) if vertical else (im.height, im.width)
    for a in range(outer):
        n = 0
        for b in range(inner):
            black = px[(a, b) if vertical else (b, a)] == 0
            if black:
                n += 1
            elif n:
                out.append(n)
                n = 0
        if n:
            out.append(n)
    return out


@pytest.mark.parametrize(
    "attrs",
    [
        "{chart=line .no-axes}",
        "{chart=line y-ticks=0 x-labels=0}",  # the axes too, no labels
        "{chart=area .no-axes height=20mm}",
        "{chart=sparkline}",
    ],
)
def test_every_stroke_is_at_least_two_dots_thick_across_it(attrs):
    two = SUPPLY.replace("| day | supply |\n|---|--:|", "| day | supply | b |\n|---|--:|--:|")
    for src in (SUPPLY, "\n".join(f"{ln} {k % 4 * 9000} |" if ln.startswith("| ") and k > 1 else ln
                                  for k, ln in enumerate(two.splitlines())) + "\n"):  # fmt: skip
        im = chart(build(src + attrs + "\n"))
        if "| b |" in src and "sparkline" not in attrs:
            im = im.crop((0, 0, im.width, im.height - 31))  # the legend (25 + 2 + 4 dots): letters, not strokes
        assert min(runs(im, True)) >= 2 and min(runs(im, False)) >= 2, attrs  # shallow and steep parts alike


def test_a_sparkline_line_is_two_dots_tall_where_it_is_shallow():
    im = chart(build("| | |\n|---|--:|\n| | 120000 |\n| | 180000 |\n| | 300000 |\n| | 749069 |\n{chart=sparkline}\n"))
    px = im.load()
    for x in (100, 200, 300):
        col = [y for y in range(im.height) if px[x, y] == 0]
        assert len(col) >= 2 and col[-1] - col[0] + 1 == len(col), x


def test_a_yearless_feb_29_after_new_year_is_not_a_crash():
    res = build("| d | n |\n|---|--:|\n| Dec 20 | 5 |\n| Feb 29 | 7 |\n| Mar 3 | 9 |\n{chart=line}\n")
    assert chart_rows(res) and "evenly spaced" in said(res, "C101")[0]


@pytest.mark.parametrize("attrs", ['{chart=line height=5mm title="Sales" }', "{chart=bar height=4px}"])
def test_a_chart_with_no_room_for_a_drawing_prints_the_table(attrs):
    src = "| d | a | b |\n|---|--:|--:|\n| x | 1 | 2 |\n| y | 3 | 4 |\n" + attrs + "\n"
    res = build(src)
    assert any("no room" in m for m in said(res, "C105")) and not chart_rows(res) and text_lines(res)


def test_numbers_from_json_and_xlsx_are_a_programs_csv_text_follows_the_locale(tmp_path):
    (tmp_path / "v.json").write_text('[{"d": "a", "v": 1.234}, {"d": "b", "v": 2}]', encoding="utf-8")
    (tmp_path / "v.csv").write_text('d,v\na,"1.234,56"\nb,2\n', encoding="utf-8")
    pt = "---\nlocale: pt-BR\n---\n| d | v |\n|---|--:|\n{chart=bar data=FILE}\n"
    assert "values read: 1.234 · 2" in said(build(pt.replace("FILE", "v.json"), base_dir=str(tmp_path)), "C101")[0]
    assert "values read: 1234.56 · 2" in said(build(pt.replace("FILE", "v.csv"), base_dir=str(tmp_path)), "C101")[0]


def test_an_empty_cell_of_a_single_series_is_a_gap_at_its_label():
    res = build("| d | n |\n|---|--:|\n| a | 1 |\n| b | |\n| c | 3 |\n{chart=line x-labels=all}\n")
    assert "3 points" in said(res, "C101")[0] and "C103" not in codes(res)
    out = "\n".join(view.lines(res.rows, res.profile))
    assert " b " in out


def test_last_with_table_prints_the_rows_of_the_points_the_chart_kept():
    rows = "".join(f"| d{i % 5} | {i} |\n" for i in range(12))
    res = build(f"| day | n |\n|---|--:|\n{rows}{{chart=bar last=2 .with-table}}\n")
    labels = [ln.split()[0] for ln in text_lines(res)[1:]]
    assert labels == ["d3", "d4", "d3", "d4"]  # rows 3, 4, 8, 9: the two labels kept, every row of each


def test_a_title_wider_than_the_chart_wraps_and_a_word_too_long_is_cut_and_said():
    res = build(SUPPLY + '{chart=line title="Daily supply of the token since the launch in January"}\n')
    out = "\n".join(view.lines(res.rows, res.profile))
    assert "Daily supply of the" in out and "January" in out and not said(res, "C105")
    res = build(SUPPLY + '{chart=line width=half title="Supercalifragilisticexpialidocious"}\n')
    assert any("title" in m and "…" in m for m in said(res, "C105"))
    long = "| d | n |\n|---|--:|\n| November the seventeenth of this year | 5 |\n{chart=bar width=half}\n"
    assert any("X label" in m and "…" in m for m in said(build(long), "C105"))


def test_table_classes_under_a_chart_without_with_table_are_said():
    res = build(SUPPLY + "{chart=line .bold .italic}\n")
    assert any(".bold" in m and ".italic" in m for m in said(res, "M101"))


def test_the_values_read_are_written_in_full_and_apart_in_a_comma_locale():
    res = build("| d | n |\n|---|--:|\n| a | 1000000 |\n| b | 1234.5678 |\n{chart=bar}\n")
    assert "values read: 1000000 · 1234.5678" in said(res, "C101")[0]
    pt = build("---\nlocale: pt-BR\n---\n| d | n |\n|---|--:|\n| a | 0,5 |\n| b | 1,6 |\n{chart=bar}\n")
    assert "y ticks 0 · 0,6 · 1,2" in said(pt, "C101")[0]


def test_the_view_never_wraps_ink_from_one_edge_to_the_other():
    from PIL import Image

    im = Image.new("1", (24, 24), 1)
    im.putpixel((23, 23), 0)
    g = charts.thicken(im)
    assert g.getpixel((0, 0)) == 255 and g.getpixel((0, 23)) == 255 and g.getpixel((23, 0)) == 255


# ---------------------------------------------------------------------------------------------------- second review


def test_a_files_number_is_a_programs_but_its_text_follows_the_locale(tmp_path):
    import openpyxl

    (tmp_path / "v.json").write_text('[{"d": "a", "v": 1.5}, {"d": "b", "v": "1.500"}]', encoding="utf-8")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["d", "v"])
    ws.append(["a", 1.234])
    ws.append(["b", "1.500"])
    wb.save(tmp_path / "v.xlsx")
    pt = "---\nlocale: pt-BR\n---\n| d | v |\n|---|--:|\n{chart=bar data=FILE}\n"
    assert "values read: 1.5 · 1500" in said(build(pt.replace("FILE", "v.json"), base_dir=str(tmp_path)), "C101")[0]
    assert "values read: 1.234 · 1500" in said(build(pt.replace("FILE", "v.xlsx"), base_dir=str(tmp_path)), "C101")[0]


def test_label_rows_without_values_at_the_ends_are_left_out_and_said():
    src = "| d | n |\n|---|--:|\n| Week 45 | |\n| Jan 1 | 0 |\n| Jan 2 | 10 |\n| Jan 31 | 0 |\n| Total | |\n"
    res = build(src + "{chart=line .no-axes}\n")
    summary = said(res, "C101")[0]
    assert "3 points" in summary and "by date" in summary
    (msg,) = said(res, "C110")
    assert "'Week 45'" in msg and "'Total'" in msg
    assert peak_x(chart(res)) < 40  # still spaced by time
    gap = "| d | n |\n|---|--:|\n| Jan 1 | 0 |\n| Jan 2 | |\n| Jan 3 | 4 |\n{chart=line}\n"
    assert "3 points" in said(build(gap), "C101")[0] and not said(build(gap), "C110")


def test_last_that_cuts_nothing_keeps_every_row_of_the_table():
    src = "| d | n |\n|---|--:|\n| a | 1 |\n| b | lots |\n| c | 3 |\n| | |\n| e | 5 |\n"
    res = build(src + "{chart=bar last=100 .with-table}\n")
    assert [ln.split()[0] for ln in text_lines(res)[1:] if ln.strip()] == ["a", "b", "c", "e"]
    res = build(src + "{chart=bar last=2 .with-table}\n")
    assert [ln.split()[0] for ln in text_lines(res)[1:] if ln.strip()] == ["c", "e"]
    res = build("| d | n |\n|---|--:|\n| a | 1 |\n| b | 2 |\n| c | lots |\n| e | 5 |\n{chart=bar last=2 .with-table}\n")
    assert [ln.split()[0] for ln in text_lines(res)[1:]] == ["b", "c", "e"]  # a row left out inside the kept range


def test_no_room_is_said_alone_and_a_tiny_sparkline_still_draws():
    rows = "".join(f"| {i} | {i % 7} |\n" for i in range(600))
    res = build(f"| x | n |\n|---|--:|\n{rows}{{chart=line height=4px}}\n")
    assert said(res, "C105") and not said(res, "C102") and not chart_rows(res)
    for h in (2, 4, 5):
        im = chart(build(f"| | |\n|---|--:|\n| | 1 |\n| | 5 |\n| | 3 |\n{{chart=sparkline height={h}px}}\n"))
        assert im.height == h and ink(im) > 0


def test_many_long_words_are_said_once():
    res = build(
        SUPPLY
        + '{chart=line width=half title="Pneumonoultramicroscopicsilicovolcanoconiosis Supercalifragilisticexpialidociousness"}\n'
    )
    assert len([m for m in said(res, "C105") if "title" in m]) == 1


def test_only_rows_and_last_rows_keep_each_rows_settings_with_it():
    from dataclasses import replace

    from bobina.model import Attrs, Run, Table

    t = Table(line=9, header=[[Run("a")]], rows=[[[Run("x")]], [[Run("y")]], [[Run("z")]]], row_lines=[2, 3],
              row_attrs=[Attrs({"bold"})])  # fmt: skip
    kept = charts.only_rows(t, [2])
    assert kept.row_lines == [9] and kept.row_attrs == [Attrs()]
    last = charts.last_rows(None, replace(t, attrs=Attrs(set(), {"last": "1"})))
    assert last.row_lines == [9] and last.row_attrs == [Attrs()]


def test_a_stroke_is_centred_on_its_point():
    from PIL import Image, ImageDraw

    im = Image.new("1", (20, 20), 1)
    charts.segment(ImageDraw.Draw(im), (5, 10), (15, 10))
    assert [y for y in range(20) if im.getpixel((10, y)) == 0] == [9, 10]
    assert [x for x in range(20) if im.getpixel((x, 10)) == 0] == list(range(4, 16))


def test_a_half_width_chart_with_small_labels_points_to_width_not_height():
    rows = "".join(f"| 2026-11-0{d} | {v} |\n" for d, v in [(2, 530), (3, 590), (4, 500), (5, 750), (6, 660)])
    src = f"| data | valor |\n|---|---|\n{rows}{{chart=bar width=half height=40mm}}\n"
    (n,) = [n for n in build(src).nudges if n.code == "C105"]
    assert "width=" in n.suggestion and "height" not in n.suggestion
    chosen = build(src.replace("height=40mm", "height=40mm size=12px"))
    assert not [n for n in chosen.nudges if n.code == "C105"]  # the small labels chosen: no note


COLD = """| hora | temp |
|---|--:|
| 00h | 2.5 |
| 06h | -0.5 |
| 09h | -1.5 |
| 12h | 0.5 |
| 18h | 4.5 |
| 21h | 3.5 |
"""


def drawn_chart(monkeypatch, src: str):
    seen = []
    draw = charts.Chart.draw
    monkeypatch.setattr(charts.Chart, "draw", lambda self, pts: (seen.append(self), draw(self, pts))[1])
    build(src)
    return seen[-1]


@pytest.mark.parametrize("y_labels", ["rotated", "horizontal"])
def test_x_labels_keep_out_of_the_y_labels_corner(monkeypatch, y_labels):
    """The first X label starts at the Y axis, not under the Y labels: the corner below the axis is theirs, so the
    lowest Y label sits on its tick instead of being pushed up against the next one (paper, 24/11)."""
    c = drawn_chart(monkeypatch, COLD + f"{{chart=area height=20mm x-labels=ends y-labels={y_labels}}}\n")
    ys = [lab for lab in c.labels_drawn if lab.kind == "y"]
    xs = [lab for lab in c.labels_drawn if lab.kind == "x"]
    axis_left = max(lab.box[0] + lab.box[2] for lab in ys)  # the Y axis is right of every Y label
    assert xs and min(lab.box[0] for lab in xs) >= axis_left
    low = max(ys, key=lambda lab: lab.box[1])  # the lowest Y label: the bottom tick, at the X axis
    assert low.box[1] + low.box[3] > c.axis_y + charts.STROKE  # it reaches into the corner, centred on its tick
    down = sorted(ys, key=lambda lab: lab.box[1])
    for a, b in zip(down, down[1:], strict=False):
        assert a.box[1] + a.box[3] <= b.box[1]  # and no two touch
