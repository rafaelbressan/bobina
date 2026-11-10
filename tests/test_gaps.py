"""Test gaps found in the review of 07/11: network guards below DNS, Excel's CSV BOM, joined columns in export
names, and which exit code wins when several parts fail."""

import socket

import pytest

from bobina import cli, datasource, sources


class _Resp:
    def __init__(self, status=200, ctype="image/png", length=None, body=b"\x89PNG"):
        self.status, self._h, self._body = status, {"Content-Type": ctype, "Content-Length": length}, body

    def getheader(self, k, default=None):
        return self._h.get(k, default)

    def read(self, n=-1):
        return self._body[:n] if n >= 0 else self._body


def _fake_conn(resp):
    class Conn:
        sock = None

        def __init__(self, host, ip, port, timeout):
            Conn.ip = ip

        def request(self, *a, **k):
            pass

        def getresponse(self):
            if isinstance(resp, Exception):
                raise resp
            return resp

        def close(self):
            pass

    return Conn


@pytest.fixture(autouse=True)
def _clear():
    sources._CACHE.clear()
    yield
    sources._CACHE.clear()


def test_the_connection_goes_to_the_checked_address(monkeypatch):
    seen = []

    def connect(addr, timeout):
        seen.append(addr)
        raise OSError("stop here")

    monkeypatch.setattr(sources, "resolve_public", lambda *a, **k: "203.0.113.7")
    monkeypatch.setattr(socket, "create_connection", connect)
    with pytest.raises(sources.ImageError) as e:
        sources.fetch("https://exemplo.org/a.png")
    assert seen == [("203.0.113.7", 443)]  # pinned: DNS is not asked again (no rebinding between check and use)
    assert e.value.code == "I101"  # an OSError becomes I101, never a traceback


@pytest.mark.parametrize(
    "resp,code,words",
    [
        (_Resp(ctype="text/html"), "I106", "not an image"),
        (_Resp(length=str(sources.MAX_BYTES + 1)), "I106", "larger than"),
        (_Resp(body=b"x" * (sources.MAX_BYTES + 1)), "I106", "larger than"),
        (_Resp(status=404), "I101", "answered 404"),
        (_Resp(status=302), "I106", "redirects"),
    ],
)
def test_download_guards(monkeypatch, resp, code, words):
    monkeypatch.setattr(sources, "resolve_public", lambda *a, **k: "203.0.113.7")
    monkeypatch.setattr(sources, "_PinnedHTTPS", _fake_conn(resp))
    with pytest.raises(sources.ImageError) as e:
        sources.fetch("https://exemplo.org/a.png")
    assert e.value.code == code and words in str(e.value)


def test_private_addresses_are_refused(monkeypatch):
    monkeypatch.setattr(sources, "_getaddrinfo", lambda *a: [(None, None, None, None, ("192.168.0.10", 443))])
    with pytest.raises(sources.ImageError) as e:
        sources.fetch("https://impressora.local/a.png")
    assert e.value.code == "I106"


def test_excel_csv_with_bom_reads_the_first_header(tmp_path):
    p = tmp_path / "excel.csv"
    p.write_bytes("﻿produto;preço\nArroz;12,5\n".encode())  # what Excel's "CSV UTF-8" writes
    rows = datasource.read_rows(p, None, [])
    assert list(rows[0]) == ["produto", "preço"] and rows[0]["produto"] == "Arroz"


def test_joined_columns_in_export_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.csv").write_text("nome\narroz\nsal\n")
    (tmp_path / "b.csv").write_text("nome,cat\narroz,graos\nsal,tempero\n")
    (tmp_path / "e.bob.md").write_text("{{ nome }}\n")
    argv = ["print", "e.bob.md", "--data", "a=a.csv", "--join", "b=b.csv", "--on", "nome", "-o", "{b.cat}-{n}.bin"]
    assert cli.main(argv) == cli.OK
    assert (tmp_path / "graos-1.bin").exists() and (tmp_path / "tempero-2.bin").exists()


def test_a_document_error_wins_over_a_usage_error_in_a_multi_part_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.bob.md").write_text("{% if %}\n")  # template syntax: a document error (E501)
    code = cli.main(["print", "--dry-run", "bad.bob.md", "--then", "missing.bob.md"])  # + file not found (E201)
    assert code == cli.DOC
