"""bobina mcp: the tools give what the CLI gives (its JSON, problem codes and exit codes), print prints only with
confirm: true, and nothing here touches a real printer (a file printer stands in for it). Skipped without the MCP
SDK, except the message that says how to install it."""

import base64
import importlib.util
import json
import os
import sys

import pytest

from bobina.cli import main

HAS_MCP = importlib.util.find_spec("mcp") is not None
needs_mcp = pytest.mark.skipif(not HAS_MCP, reason="the MCP SDK is not installed (pip install -e '.[mcp]')")
PIX = "# Bakery\n\n```pay {scheme=pix}\n```\n"  # a pay block without to=: Q111, exit 9


def test_without_the_sdk_bobina_mcp_says_how_to_install_it(monkeypatch, capsys):
    for name in ("mcp", "mcp.server", "mcp.server.mcpserver"):
        monkeypatch.setitem(sys.modules, name, None)
    assert main(["mcp"]) == 1
    e = capsys.readouterr().err
    assert "E101" in e and "uv tool install 'bobina[mcp]'" in e


def call(tool, args=None, **server):
    import anyio
    from mcp import Client

    from bobina.mcp_server import build

    async def go():
        async with Client(build(**server)) as c:
            return await c.call_tool(tool, args or {})

    return anyio.run(go)


def texts(r) -> list[str]:
    return [c.text for c in r.content if c.type == "text"]


def output(r) -> dict:
    """The CLI's JSON: the text after the command line."""
    return json.loads(texts(r)[1])


@pytest.fixture
def file_printer(tmp_path):
    out = tmp_path / "out.bin"
    assert main(["printer", "add", "test", "--path", str(out), "--default"]) == 0
    return out


@needs_mcp
def test_the_tools_and_print_is_not_read_only():
    import anyio
    from mcp import Client

    from bobina.mcp_server import build

    async def go():
        async with Client(build()) as c:
            return {t.name: t for t in (await c.list_tools()).tools}

    tools = anyio.run(go)
    assert set(tools) == {"check", "preview", "print", "template_list", "template_show", "help", "status", "paper"}
    assert tools["check"].annotations.read_only_hint is True
    assert tools["print"].annotations.read_only_hint is False
    assert tools["print"].input_schema["properties"]["confirm"]["default"] is False


@needs_mcp
def test_check_gives_the_json_of_check_and_its_exit_code():
    r = call("check", {"text": "# Market\n- [ ] milk"})
    assert not r.is_error
    assert texts(r)[0] == "bobina check - --json\nexit 0 (ok)"
    assert output(r)["stats"]["profile"] == "mtp-ii-58"


@needs_mcp
def test_a_payment_code_left_out_is_exit_9_and_not_an_error():
    r = call("check", {"text": PIX})
    assert not r.is_error and "exit 9" in texts(r)[0]
    assert [p["code"] for p in output(r)["problems"]] == ["Q111"]
    r = call("check", {"text": PIX, "allow": ["Q111"]})
    assert "exit 0" in texts(r)[0] and output(r)["problems"] == []


@needs_mcp
def test_check_a_file_and_a_missing_file_is_never_printed_as_text(tmp_path):
    doc = tmp_path / "list.bob.md"
    doc.write_text("# List\n- bread\n")
    assert not call("check", {"path": str(doc)}).is_error
    r = call("check", {"path": str(tmp_path / "missing.bob.md")})
    assert r.is_error and "file not found" in texts(r)[0]
    assert call("check", {}).is_error  # neither text nor path
    assert call("check", {"text": "x", "path": str(doc)}).is_error  # both


@needs_mcp
def test_print_without_confirm_is_a_dry_run(file_printer):
    r = call("print", {"text": "# Hello"})
    assert not r.is_error
    assert "--dry-run" in texts(r)[0] and "--yes" not in texts(r)[0]
    assert output(r)["outcome"] == "dry run"
    assert "nothing was printed" in texts(r)[-1]
    assert not file_printer.exists() or file_printer.read_bytes() == b""
    r = call("print", {"text": "# Hello", "confirm": False})
    assert output(r)["outcome"] == "dry run" and not file_printer.exists()


@needs_mcp
def test_print_with_confirm_prints_on_the_configured_printer(file_printer):
    r = call("print", {"text": "# Hello", "confirm": True})
    assert not r.is_error, texts(r)
    out = output(r)
    assert out["schema"] == "bobina.print/1" and out["outcome"] == "printed" and out["printer"] == "test"
    assert b"Hello" in file_printer.read_bytes()


@needs_mcp
def test_print_with_confirm_and_no_printer_is_e401_exit_4():
    r = call("print", {"text": "# Hello", "confirm": True})
    assert r.is_error and "exit 4" in texts(r)[0]
    assert "E401" in "\n".join(texts(r))


@needs_mcp
def test_print_without_the_payment_code_is_exit_9_and_still_prints(file_printer):
    r = call("print", {"text": PIX, "confirm": True})
    assert not r.is_error and "exit 9" in texts(r)[0]
    assert output(r)["exit"] == 9 and file_printer.read_bytes()


@needs_mcp
def test_the_server_printer_is_the_default_of_print(tmp_path):
    other = tmp_path / "other.bin"
    assert main(["printer", "add", "other", "--path", str(other)]) == 0
    r = call("print", {"text": "# Hi", "confirm": True}, printer="other")
    assert output(r)["printer"] == "other" and other.read_bytes()


@needs_mcp
def test_allow_and_strict_of_the_server_apply_to_every_call():
    assert "exit 0" in texts(call("check", {"text": PIX}, allow=["Q111"]))[0]
    r = call("check", {"text": PIX}, strict=True)
    assert r.is_error and "exit 3" in texts(r)[0] and "--strict" in texts(r)[0]


@needs_mcp
def test_preview_returns_the_png_and_its_path(tmp_path):
    r = call("preview", {"text": "# Hello\n\n```qr\nhttps://example.com\n```"})
    assert not r.is_error
    files = output(r)["files"]
    assert len(files) == 1 and os.path.isfile(files[0])
    (image,) = [c for c in r.content if c.type == "image"]
    assert image.mime_type == "image/png" and base64.b64decode(image.data)[:8] == b"\x89PNG\r\n\x1a\n"
    mine = tmp_path / "mine.png"
    r = call("preview", {"text": "# Hello", "output": str(mine)})
    assert output(r)["files"] == [str(mine)] and mine.is_file()


@needs_mcp
def test_network_images_need_allow_net():
    r = call("check", {"text": "![logo](https://example.com/logo.png)"})
    assert "I103" in [p["code"] for p in output(r)["problems"]]


@needs_mcp
def test_values_never_become_options(file_printer):
    r = call("print", {"text": "{{ y }}", "set": {"-y": "1", "y": "--yes"}})
    assert output(r)["outcome"] == "dry run" and not file_printer.exists()
    assert call("template_show", {"name": "--yes"}).is_error
    assert call("help", {"topic": "-x"}).is_error


@needs_mcp
def test_templates():
    assert "receipt" in output(call("template_list"))
    r = call("template_show", {"name": "receipt"})
    assert "items" in output(r) and "bobina template new receipt" in texts(r)[-1]
    r = call("template_show", {"name": "nonexistent"})
    assert r.is_error


@needs_mcp
def test_help_a_problem_code_and_a_pay_scheme():
    assert output(call("help", {"topic": "Q111"}))["code"] == "Q111"
    assert output(call("help", {"topic": "pay", "name": "pix"}))["kind"] == "pay-scheme"
    r = call("help", {"topic": "nonsense"})
    assert r.is_error and "E207" in "\n".join(texts(r))


@needs_mcp
def test_status_and_paper_say_what_the_cli_says():
    for tool in ("status", "paper"):
        r = call(tool)
        assert r.is_error and "exit 4" in texts(r)[0] and "E401" in "\n".join(texts(r))


@needs_mcp
def test_status_of_a_file_printer_is_e404(file_printer):
    r = call("status")
    assert r.is_error and "E404" in "\n".join(texts(r))


def test_a_child_never_waits_for_a_terminal():
    """BOBINA_NONINTERACTIVE: a print without --yes stops at once with E107 (no question on any terminal)."""
    from bobina.mcp_server import run

    r = run(["print", "-"], "# Hello")
    assert r.code == 7 and "E107" in r.stderr


@needs_mcp
def test_over_stdio_stdout_carries_only_the_protocol():
    import anyio
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "bobina", "mcp"], env=dict(os.environ))

    async def go():
        async with Client(params) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            return names, await c.call_tool("check", {"text": "# Hi"})

    names, r = anyio.run(go)
    assert "print" in names and not r.is_error
