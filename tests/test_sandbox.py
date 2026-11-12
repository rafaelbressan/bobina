"""--sandbox (always on in the MCP server): a document's images only from its own folder and image_dirs in
config.toml, wherever a path or a symlink points; the terminal without --sandbox reads them as before.
Nothing here prints: check, preview and a file printer only."""

import importlib.util
import json

import pytest
from PIL import Image

from bobina import cli
from bobina.engine import build
from bobina.rows import BitmapRow

HAS_MCP = importlib.util.find_spec("mcp") is not None


def images(res):
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]


def codes(res):
    return {n.code for n in res.nudges}


@pytest.fixture
def place(tmp_path, monkeypatch):
    """docs/ (the document's folder) with in.png, elsewhere/secret.png, a home with Pictures/p.png."""
    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    docs, elsewhere = tmp_path / "docs", tmp_path / "elsewhere"
    docs.mkdir()
    elsewhere.mkdir()
    for p in (docs / "in.png", elsewhere / "secret.png", home / "Pictures" / "p.png"):
        Image.new("L", (40, 20), 0).save(p)
    return tmp_path


def doc(place, body: str):
    p = place / "docs" / "d.bob.md"
    p.write_text(body + "\n")
    return str(p)


def check(argv, capsys):
    code = cli.main(["check", *argv, "--json"])
    out = json.loads(capsys.readouterr().out)
    return code, {p["code"] for p in out["problems"]}


def image_dirs(place, *dirs):
    cfg = place / "config" / "config.toml"
    cfg.write_text(cfg.read_text() + "image_dirs = [" + ", ".join(json.dumps(d) for d in dirs) + "]\n")


def test_the_terminal_without_sandbox_reads_images_anywhere(place):
    secret = place / "elsewhere" / "secret.png"
    res = build(f"![]({secret})\n\n![](../elsewhere/secret.png)", base_dir=str(place / "docs"))
    assert len(images(res)) == 2 and "I108" not in codes(res)


@pytest.mark.parametrize(
    "src",
    [
        "{elsewhere}/secret.png",
        "../elsewhere/secret.png",
        "~/Pictures/p.png",
        "link.png",
        "sub/../../elsewhere/secret.png",
    ],
)
def test_sandbox_leaves_out_images_outside_the_folder(place, src):
    (place / "docs" / "link.png").symlink_to(place / "elsewhere" / "secret.png")  # inside by name, outside in fact
    res = build(
        f"![]({src.format(elsewhere=place / 'elsewhere')})",
        base_dir=str(place / "docs"),
        image_dirs=(str(place / "docs"),),
    )
    assert not images(res) and "I108" in codes(res)
    n = next(n for n in res.nudges if n.code == "I108")
    assert "image_dirs" in n.suggestion


def test_sandbox_reads_the_document_folder_and_image_dirs(place):
    (place / "docs" / "inside.png").symlink_to(place / "docs" / "in.png")  # a symlink that stays inside
    body = "![](in.png)\n\n![](inside.png)\n\n```image\nin.png\n```\n\n![](~/Pictures/p.png)"
    res = build(body, base_dir=str(place / "docs"), image_dirs=(str(place / "docs"), "~/Pictures"))
    assert len(images(res)) == 4 and "I108" not in codes(res)


def test_sandbox_keeps_data_uris_and_leaves_the_network_to_allow_net(place):
    import base64
    import io

    buf = io.BytesIO()
    Image.new("L", (8, 8), 0).save(buf, format="PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    res = build(f"![]({uri})\n\n![](https://example.com/a.png)", base_dir=str(place), image_dirs=())
    assert len(images(res)) == 1 and "I103" in codes(res) and "I108" not in codes(res)


def test_the_sandbox_option_on_the_command_line(place, capsys):
    d = doc(place, f"![](in.png)\n\n![]({place / 'elsewhere' / 'secret.png'})")
    assert check([d], capsys)[1] == set()
    code, found = check([d, "--sandbox"], capsys)
    assert "I108" in found and code == cli.OK  # a warning: the rest of the document is still checked
    image_dirs(place, str(place / "elsewhere"))
    assert "I108" not in check([d, "--sandbox"], capsys)[1]


def test_sandbox_with_stdin_or_inline_text_has_no_document_folder(place, capsys, monkeypatch):
    import io
    import sys

    monkeypatch.chdir(place / "docs")  # in.png is right here, but text has no folder of its own
    monkeypatch.setattr(sys, "stdin", io.StringIO("![](in.png)\n"))
    assert "I108" in check(["-", "--sandbox"], capsys)[1]
    assert "I108" in check(["![](in.png)", "--sandbox"], capsys)[1]
    image_dirs(place, str(place / "docs"))
    assert "I108" not in check(["![](in.png)", "--sandbox"], capsys)[1]


def test_sandbox_preview_and_print_leave_the_image_out(place, capsys):
    d = doc(place, f"text\n\n![]({place / 'elsewhere' / 'secret.png'})")
    out = place / "o.bin"
    assert cli.main(["print", d, "--sandbox", "-o", str(out)]) == cli.OK
    with_image = place / "o2.bin"
    assert cli.main(["print", d, "-o", str(with_image)]) == cli.OK
    assert len(out.read_bytes()) < len(with_image.read_bytes())
    assert cli.main(["preview", d, "--sandbox", "-o", str(place / "p.png")]) == cli.OK
    assert "I108" in capsys.readouterr().err


@pytest.mark.skipif(not HAS_MCP, reason="the MCP SDK is not installed (pip install -e '.[mcp]')")
def test_the_mcp_document_tools_run_sandboxed(place):
    import anyio
    from mcp import Client

    from bobina.mcp_server import build as mcp_build

    def call(tool, args):
        async def go():
            async with Client(mcp_build()) as c:
                return await c.call_tool(tool, args)

        r = anyio.run(go)
        texts = [c.text for c in r.content if c.type == "text"]
        assert "--sandbox" in texts[0].splitlines()[0]  # the command line it ran
        return {p["code"] for p in json.loads(texts[1])["problems"]}

    secret = place / "elsewhere" / "secret.png"
    d = doc(place, f"![](in.png)\n\n![]({secret})")
    assert call("check", {"path": d}) == {"I108"}  # in.png (its folder) is read, secret.png is not
    assert "I108" in call("check", {"text": "![](in.png)"})  # text: no folder, and no image_dirs yet
    image_dirs(place, str(place / "elsewhere"))
    assert "I108" not in call("check", {"text": f"![]({secret})"})


def test_mcp_server_passes_sandbox_to_every_document_tool(monkeypatch):
    anyio = pytest.importorskip("anyio")
    from bobina import mcp_server

    runs = []

    async def run(argv, stdin=None, timeout=mcp_server.TIMEOUT):
        runs.append(argv)
        return mcp_server.Run(argv, 0, "{}", "")

    monkeypatch.setattr(mcp_server, "run", run)
    monkeypatch.setattr(mcp_server, "result", lambda r, *extra: r)
    monkeypatch.setattr(mcp_server, "_images", lambda files: [])
    s = mcp_server.Server()
    for tool in (s.check, s.preview, s.print):
        anyio.run(lambda t=tool: t(text="x"))
    assert [argv[0] for argv in runs] == ["check", "preview", "print"]
    assert all("--sandbox" in argv for argv in runs)
