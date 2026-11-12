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


@pytest.mark.parametrize("scheme", ["ſſ", "KK"])  # ſ and the Kelvin sign: letters only to (?i)
def test_a_unicode_lookalike_of_a_scheme_is_a_path_and_stays_confined(place, scheme):
    from bobina import sources

    (place / "docs" / f"{scheme}:").mkdir()  # shipped in the shared folder, so the path resolves
    src = f"{scheme}:/../../elsewhere/secret.png"
    res = build(f"![]({src})", base_dir=str(place / "docs"), image_dirs=(str(place / "docs"),))
    assert not images(res) and "I108" in codes(res)
    with pytest.raises(sources.ImageError) as e:  # the check is where files are read, for any caller
        sources.load(src, str(place / "docs"), confine=((place / "docs").resolve(),))
    assert e.value.code == "I108"


def test_the_i108_hint_is_valid_toml_with_forward_slashes(place):
    import tomllib

    res = build("![](../elsewhere/secret.png)", base_dir=str(place / "docs"), image_dirs=(str(place / "docs"),))
    hint = next(n for n in res.nudges if n.code == "I108").suggestion
    line = hint[hint.index("image_dirs") :]
    assert tomllib.loads(line)["image_dirs"] == [(place / "elsewhere").resolve().as_posix()]


def test_sandbox_given_in_any_part_covers_the_whole_job(place, capsys):
    secret = place / "elsewhere" / "secret.png"
    first, second = doc(place, f"![]({secret})"), str(place / "docs" / "e.bob.md")
    (place / "docs" / "e.bob.md").write_text(f"![]({secret})\n")
    for argv in ([first, "--then", second, "--sandbox"], [first, "--sandbox", "--then", second]):
        cli.main(["check", *argv, "--json"])
        out = json.loads(capsys.readouterr().out)
        assert [p["code"] for p in out["problems"]].count("I108") == 2, argv


def test_relative_image_dirs_are_relative_to_config_toml(place, capsys, monkeypatch):
    pics = place / "config" / "pics"
    pics.mkdir()
    Image.new("L", (8, 8), 0).save(pics / "logo.png")
    image_dirs(place, "pics")
    monkeypatch.chdir(place / "elsewhere")  # not where config.toml is
    d = doc(place, f"![]({pics / 'logo.png'})")
    assert "I108" not in check([d, "--sandbox"], capsys)[1]


@pytest.mark.parametrize("value", ['"~/Pictures"', "[1, 2]", '[""]', "true"])
def test_image_dirs_that_is_not_a_list_of_folders_is_a_clear_error(place, capsys, value):
    cfg = place / "config" / "config.toml"
    cfg.write_text(cfg.read_text() + f"image_dirs = {value}\n")
    assert cli.main(["check", doc(place, "hi"), "--sandbox"]) == cli.USAGE
    e = capsys.readouterr().err
    assert "image_dirs" in e and "E101" in e and "list of folders" in e


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="RLIMIT_AS is enforced on Linux")
def test_a_sandboxed_run_has_a_memory_ceiling(place):
    import os
    import subprocess
    import sys

    d = doc(place, "hi")
    code = (
        "import resource, sys; from bobina.cli import main; main(['check', sys.argv[1], '--sandbox', '-q']);"
        " print(resource.getrlimit(resource.RLIMIT_AS)[0])"
    )
    env = {k: v for k, v in os.environ.items() if k != "BOBINA_MEMORY_LIMIT"}
    out = subprocess.run([sys.executable, "-c", code, d], capture_output=True, text=True, env=env, timeout=60)
    assert int(out.stdout.split()[-1]) == 2 * 1024**3, out.stderr
    plain = subprocess.run(
        [sys.executable, "-c", code.replace(", '--sandbox'", ""), d], capture_output=True, text=True, env=env
    )
    assert int(plain.stdout.split()[-1]) != 2 * 1024**3  # without --sandbox, no ceiling of bobina's


def test_running_out_of_memory_is_m313_not_a_traceback(place, capsys, monkeypatch):
    from bobina import engine

    def huge(*a, **k):
        raise MemoryError

    monkeypatch.setattr(engine, "build_batch", huge)
    assert cli.main(["check", doc(place, "hi"), "--sandbox"]) == cli.SECURITY
    e = capsys.readouterr().err
    assert "M313" in e and "nothing was printed" in e
