"""--compact strips and --then jobs: one preview, one confirmation, one tear feed."""

from bobina import cli


def tears(*argv) -> int:
    """Feeds to the tear bar in the job, counted on its rows (counting ESC J @ in the bytes would also count raster
    data that happens to contain those bytes)."""
    from bobina.cli import args as cargs
    from bobina.cli import common
    from bobina.rows import FeedRow

    res, *_ = common.load_job(cargs.parse_args(cargs.make_parser(), ["print", *argv]))
    n = sum(1 for r in res.all_rows if isinstance(r, FeedRow) and r.mark == "tear")
    assert n == res.joins.count("tear") + 1 if hasattr(res, "joins") else n == 1  # the rows agree with the joins
    feed = b"\x1bJ" + bytes([int(res.profile.get("margins.feed_after_dots", 64))])
    labels = [res] if not hasattr(res, "labels") else res.labels
    if not getattr(res, "stripped", False):  # each label's bytes end with its own feed to the tear bar
        assert all(lab.data.rstrip(b"\x00").endswith(feed) or feed in lab.data[-16:] for lab in labels)
    else:
        assert feed in res.data[-16:]  # one strip: the feed at the end
    return n


def out(tmp_path, *argv):
    o = tmp_path / "o.bin"
    code = cli.main(["print", *argv, "-o", str(o), "--force"])
    return code, (o.read_bytes() if o.exists() else b"")


def data_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("item,n\nrice,2\nbeans,1\nsalt,0\n")
    (tmp_path / "row.bob.md").write_text("{{ item }}\n")
    return str(p), str(tmp_path / "row.bob.md")


def test_compact_batch_has_one_tear_feed_and_is_shorter(tmp_path):
    d, row = data_csv(tmp_path)
    _, normal = out(tmp_path, row, "--data", d)
    code, compact = out(tmp_path, row, "--data", d, "--compact")
    assert code == cli.OK
    assert tears(row, "--data", d) == 3 and tears(row, "--data", d, "--compact") == 1
    assert compact.count(b"\x1b@") == 1 and len(compact) < len(normal) + 2000  # one job, cut lines as raster
    for item in (b"rice", b"beans", b"salt"):
        assert item in compact


def test_then_joins_documents_with_their_own_options(tmp_path):
    d, row = data_csv(tmp_path)
    code, data = out(
        tmp_path, row, "--data", d, "--where", "n!=0", "--then", row, "--data", d, "--copies-from", "n", "--then", "fim"
    )
    assert code == cli.OK
    assert data.count(b"rice") == 1 + 2 and data.count(b"salt") == 0
    assert data.index(b"beans") < data.rindex(b"rice") < data.index(b"fim")
    argv = (row, "--data", d, "--where", "n!=0", "--then", row, "--data", d, "--copies-from", "n", "--then", "fim")
    assert tears(*argv) == 2 + 3 + 1  # not compact: every label keeps its tear feed


def test_compact_all_written_in_a_later_part(tmp_path):
    _, data = out(tmp_path, "one", "--then", "two", "--compact-all")
    assert tears("one", "--then", "two", "--compact-all") == 1 and data.index(b"one") < data.index(b"two")


def test_counters_continue_across_parts(tmp_path):
    _, data = out(tmp_path, "#{{ seq.t }}", "--then", "#{{ seq.t }}")
    assert b"#1" in data and b"#2" in data


def test_then_without_a_document_is_an_error(tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        cli.main(["print", "one", "--then"])
