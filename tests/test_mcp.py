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
    assert set(tools) == {
        "check",
        "preview",
        "print",
        "template_list",
        "template_show",
        "help",
        "status",
        "paper",
        "paper_new",
    }
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
def test_paper_new_needs_the_length_with_its_unit(file_printer):
    """The roll the user said they loaded: never a default roll, never a bare number."""
    for bad in ("", "30", "-30m", "30m --remember"):
        r = call("paper_new", {"length": bad})
        assert r.is_error and "with its unit" in texts(r)[0]
    r = call("paper_new", {"length": "30m"})
    assert not r.is_error and "exit 0" in texts(r)[0]
    r = call("paper")
    assert not r.is_error and "30" in "\n".join(texts(r))
    r = call("paper_new", {})  # no size: the agent asks, never a usual roll
    assert r.is_error and "ask the user" in texts(r)[0]
    assert output(call("paper_new", {"length": "50ft"}))["roll_mm"] == 15240


@needs_mcp
def test_paper_new_a_package_code_is_a_question_for_the_user(file_printer):
    for code in ("57x30", "80 x 40"):
        msg = texts(call("paper_new", {"length": code}))[0]
        assert "Ask the user one question" in msg and "metres" in msg and "diameter in mm" in msg
    msg = texts(call("paper_new", {"length": "2 1/4\" x 50'"}))[0]  # units on both: split, nothing to ask
    assert 'length "50ft", width "2 1/4in"' in msg


@needs_mcp
def test_paper_new_from_the_diameter_and_a_width_that_does_not_fit(file_printer):
    r = call("paper_new", {"diameter": "40mm", "core": "12mm", "width": "57mm"})
    assert not r.is_error and "--diameter=40mm --core=12mm --width=57mm" in texts(r)[0]
    assert 18_000 < output(r)["roll_mm"] < 20_000 and "P103" not in "\n".join(texts(r))
    r = call("paper_new", {"length": "40m", "width": "80mm"})  # recorded, with a warning
    assert not r.is_error and output(r)["roll_mm"] == 40000
    assert [p["code"] for p in output(r)["problems"]] == ["P103"]
    for bad in ({"length": "30m", "diameter": "40mm"}, {"length": "30m", "core": "12mm"}, {"diameter": "40"},
                {"length": "0m"}):  # fmt: skip
        assert call("paper_new", bad).is_error


@needs_mcp
def test_paper_new_uses_the_servers_profile_allow_and_strict(file_printer):
    """P103 judged as prints are: bobina mcp --profile, --allow and --strict."""
    r = call("paper_new", {"length": "40m", "width": "80mm"}, profile="epson-tm-t70-sa")  # an 80 mm printer
    assert "--profile=epson-tm-t70-sa" in texts(r)[0] and "problems" not in output(r)
    r = call("paper_new", {"length": "40m", "width": "80mm"}, allow=["P103"])
    assert not r.is_error and "problems" not in output(r)
    r = call("paper_new", {"length": "20m", "width": "80mm"}, strict=True)  # stopped: the roll is not recorded
    assert r.is_error and "exit 3" in texts(r)[0] and output(r)["roll_mm"] == 40000


@needs_mcp
def test_status_of_a_file_printer_is_e404(file_printer):
    r = call("status")
    assert r.is_error and "E404" in "\n".join(texts(r))


@needs_mcp
def test_a_child_never_waits_for_a_terminal():
    """BOBINA_NONINTERACTIVE: a print without --yes stops at once with E107 (no question on any terminal)."""
    import anyio

    from bobina.mcp_server import run

    r = anyio.run(run, ["print", "-"], "# Hello")
    assert r.code == 7 and "E107" in r.stderr


linux = pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="reads /proc to see the printer command end")


@pytest.fixture
def slow_printer(tmp_path):
    """A command printer that never finishes (it writes its pid, then sleeps): a print stuck on the printer."""
    pid = tmp_path / "pid"
    assert main(["printer", "add", "slow", "--command", f"sh -c 'echo $$ > {pid}; exec sleep 60'", "--default"]) == 0
    return pid


def _ended(pidfile, wait=10.0) -> bool:
    """The printer command started and is no longer running (gone, or a zombie waiting to be reaped)."""
    import time

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if pidfile.exists() and pidfile.read_text().strip():
            status = f"/proc/{pidfile.read_text().strip()}/status"
            try:
                with open(status) as f:
                    if "\nState:\tZ" in f.read():
                        return True
            except FileNotFoundError:
                return True
        time.sleep(0.1)
    return False


@needs_mcp
@linux
def test_a_print_that_does_not_finish_is_stopped_with_its_command_and_says_so(slow_printer, monkeypatch):
    """Never 'exit 1 (usage)': an agent would read a bad call and print again. The command the printer runs (its
    process group) is stopped too."""
    from bobina import mcp_server

    monkeypatch.setattr(mcp_server, "TIMEOUT", 4)
    monkeypatch.setattr(mcp_server, "GRACE", 1)
    r = call("print", {"text": "# Hello", "confirm": True})
    head = texts(r)[0]
    assert r.is_error and "no exit code, stopped after 4 s" in head and "exit 1" not in head
    assert "may already be on paper" in head and "bobina history" in head
    assert _ended(slow_printer)


@needs_mcp
@linux
def test_a_cancelled_print_stops_its_process_group(slow_printer, monkeypatch, capsys):
    import anyio

    from bobina import mcp_server

    monkeypatch.setattr(mcp_server, "GRACE", 1)
    s = mcp_server.Server()

    async def go():
        with anyio.move_on_after(4):  # the client cancels the call
            await s.print(text="# Hello", confirm=True)
            return "finished"
        return "cancelled"

    assert anyio.run(go) == "cancelled"
    assert _ended(slow_printer)
    e = capsys.readouterr().err
    assert "the call was cancelled" in e and "may already be on paper" in e


@needs_mcp
def test_check_and_preview_use_the_printer_print_will_use(file_printer, tmp_path):
    assert main(["printer", "add", "wide", "--path", str(tmp_path / "w.bin"), "--profile", "epson-tm-t70"]) == 0
    assert output(call("check", {"text": "# Hi"}))["stats"]["profile"] == "mtp-ii-58"
    assert output(call("check", {"text": "# Hi", "printer": "wide"}))["stats"]["profile"] == "epson-tm-t70"
    r = call("preview", {"text": "# Hi", "printer": "wide"})
    assert "--printer=wide" in texts(r)[0] and output(r)["stats"]["profile"] == "epson-tm-t70"
    assert output(call("check", {"text": "# Hi"}, printer="wide"))["stats"]["profile"] == "epson-tm-t70"


@needs_mcp
def test_a_preview_of_several_labels_returns_every_one(tmp_path, monkeypatch):
    rows = tmp_path / "rows.csv"
    rows.write_text("item\nrice\nbeans\nflour\n")
    pattern = str(tmp_path / "out" / "label-{n}.png")
    r = call("preview", {"text": "# {{ item }}", "data": str(rows), "output": pattern})
    files = output(r)["files"]
    assert len(files) == 3 and all(os.path.isfile(f) for f in files)
    assert len([c for c in r.content if c.type == "image"]) == 3
    listing = next(t for t in texts(r) if "file(s) written" in t)
    assert all(f in listing for f in files)
    from bobina import mcp_server

    monkeypatch.setattr(mcp_server, "IMAGES_MAX", 2)
    r = call("preview", {"text": "# {{ item }}", "data": str(rows), "output": str(tmp_path / "b-{n}.png")})
    assert len([c for c in r.content if c.type == "image"]) == 2
    listing = next(t for t in texts(r) if "file(s) written" in t)
    assert "not attached" in listing and output(r)["files"][2] in listing.split("not attached")[1]


@needs_mcp
def test_field_names_and_data_paths_are_checked(tmp_path):
    for bad in ({"": "x"}, {" ": "x"}, {"a=b": "x"}):
        r = call("check", {"text": "# {{ a }}", "set": bad})
        assert r.is_error and "E304" in texts(r)[0], bad
    odd = tmp_path / "a=b.csv"
    odd.write_text("item\nrice\n")
    r = call("check", {"text": "# {{ item }}", "data": str(odd)})
    assert r.is_error and "NAME=FILE" in texts(r)[0]
    rows = tmp_path / "rows.csv"
    rows.write_text("item\nrice\n")
    r = call("check", {"text": "# {{ src.item }}", "data": f"src={rows}"})
    assert not r.is_error, texts(r)


@needs_mcp
def test_a_path_with_at_is_a_file_when_one_exists_else_a_saved_label(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "@shelf.bob.md").write_text("# Shelf\n")
    r = call("check", {"path": "@shelf.bob.md"})
    assert not r.is_error and str(tmp_path / "@shelf.bob.md") in texts(r)[0]
    r = call("check", {"path": "@nothing"})
    assert r.is_error and "check @nothing" in texts(r)[0] and "E206" in "\n".join(texts(r))
    assert main(["library", "add", "bread", "# BREAD"]) == 0
    assert not call("check", {"path": "@bread"}).is_error
    r = call("check", {"path": "@bad name"})
    assert r.is_error and "E206" in texts(r)[0]


@needs_mcp
def test_the_temporary_previews_go_with_the_server():
    import anyio

    from bobina import mcp_server

    s = mcp_server.Server()
    anyio.run(lambda: s.preview(text="# Hi"))
    folder = s.previews
    assert folder is not None and any(folder.iterdir())
    s.cleanup()
    assert not folder.exists() and s.previews is None


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
