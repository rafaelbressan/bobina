"""bobina update and the once-a-day notice: the newest release from PyPI (faked here, never asked), what installed
bobina and its upgrade command, never replacing its own files, and silence for agents, scripts and pipes."""

import json
import time

import pytest

from bobina import cli, update
from bobina.cli import update as cli_update

PYPI = {
    "info": {"version": "0.1.4"},
    "releases": {
        "0.1.2": [{"yanked": False}],
        "0.1.3": [{"yanked": False}],
        "0.1.4": [{"yanked": False}],
        "0.2.0rc1": [{"yanked": False}],
        "0.1.9": [{"yanked": True}],
        "0.1.8": [],
    },
}


@pytest.fixture
def pypi(monkeypatch):
    calls = []

    def fake(timeout=update.TIMEOUT):
        calls.append(timeout)
        return update.newest(PYPI)

    monkeypatch.setattr(update, "fetch", fake)
    return calls


@pytest.fixture
def version(monkeypatch):
    def set_(v):
        monkeypatch.setattr(update, "__version__", v)
        monkeypatch.setattr(cli_update, "__version__", v)

    set_("0.1.3")
    return set_


# --------------------------------------------------------------- versions


def test_only_stable_releases_with_files_count():
    assert update.newest(PYPI) == "0.1.4"  # not the rc, the yanked 0.1.9 or the empty 0.1.8
    assert update.parse("0.1.0.dev0") is None and update.parse("0.2.0rc1") is None
    assert update.newer("0.1.10", "0.1.9") and not update.newer("0.1.3", "0.1.3")
    assert not update.newer("0.1.4", "0.1.0.dev0")  # a development build is never told to upgrade


# --------------------------------------------------------------- what installed it


def test_each_installer_gets_its_own_command(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "_direct_url", lambda: None)
    uv = tmp_path / "uv" / "tools" / "bobina"
    uv.mkdir(parents=True)
    (uv / "uv-receipt.toml").write_text("[tool]\n")
    assert update.detect(prefix=str(uv), module="/x/bobina").command == ["uv", "tool", "upgrade", "bobina"]
    pipx = "/home/a/.local/share/pipx/venvs/bobina"
    assert update.detect(prefix=pipx, module="/x/bobina").command == ["pipx", "upgrade", "bobina"]
    brew = "/opt/homebrew/Cellar/bobina/0.1.3/libexec"
    assert update.detect(prefix=brew, module="/x").shown == "brew upgrade rafaelbressan/bobina/bobina"
    deb = update.detect("0.1.4", prefix="/usr", module="/usr/lib/bobina/common/bobina")
    assert deb.command is None and "sudo apt install ./bobina_0.1.4_" in deb.shown
    assert "/releases/download/v0.1.4/bobina_0.1.4_" in deb.shown


def test_a_git_install_says_so_and_points_at_the_release(monkeypatch, tmp_path):
    uv = tmp_path / "tools" / "bobina"
    uv.mkdir(parents=True)
    (uv / "uv-receipt.toml").write_text("[tool]\n")
    monkeypatch.setattr(update, "_direct_url", lambda: {"url": "git+https://github.com/x/bobina", "vcs_info": {}})
    how = update.detect(prefix=str(uv), module="/x")
    assert how.kind == "git" and how.command is None and "uv tool install --force --python" in how.shown
    monkeypatch.setattr(update, "_direct_url", lambda: {"url": "file:///src", "dir_info": {"editable": True}})
    assert update.detect(prefix=str(uv), module="/x").kind == "dev"


# --------------------------------------------------------------- bobina update


def test_update_says_the_command_and_never_runs_it_without_a_terminal(pypi, version, monkeypatch, capsys):
    monkeypatch.setattr(cli_update, "open_tty", lambda: None)
    monkeypatch.setattr(
        update,
        "detect",
        lambda latest=None: update.Install("pipx", "pipx", ["pipx", "upgrade", "bobina"], "pipx upgrade bobina"),
    )
    ran = []
    monkeypatch.setattr(cli_update.subprocess, "call", lambda c: ran.append(c) or 0)
    assert cli.main(["update"]) == cli.OK
    out = capsys.readouterr().out
    assert "bobina 0.1.4 is available (you have 0.1.3)" in out and "installed by pipx: pipx upgrade bobina" in out
    assert ran == []


def test_update_runs_the_installer_only_after_yes(pypi, version, monkeypatch, capsys):
    from test_steps import FakeTTY

    monkeypatch.setattr(
        update,
        "detect",
        lambda latest=None: update.Install(
            "uv", "uv tool", ["uv", "tool", "upgrade", "bobina"], "uv tool upgrade bobina"
        ),
    )
    ran = []
    monkeypatch.setattr(cli_update.subprocess, "call", lambda c: ran.append(c) or 0)
    monkeypatch.setattr(cli_update, "_person", lambda: True)
    monkeypatch.setattr(cli_update, "open_tty", lambda: FakeTTY("n"))
    assert cli.main(["update"]) == cli.OK and ran == []
    monkeypatch.setattr(cli_update, "open_tty", lambda: FakeTTY("y"))
    assert cli.main(["update"]) == cli.OK and ran == [["uv", "tool", "upgrade", "bobina"]]


def test_update_check_and_json(pypi, version, capsys):
    assert cli.main(["update", "--check"]) == cli.NEWER
    capsys.readouterr()
    assert cli.main(["update", "--json"]) == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "bobina.update/1" and doc["newer"] is True and doc["latest"] == "0.1.4"
    from test_schemas import _check, _schema

    _check(doc, _schema("update"))
    version("0.1.4")
    assert cli.main(["update", "--check"]) == cli.OK
    assert "is the latest release" in capsys.readouterr().out


def test_update_offline_is_a_clear_error(version, capsys):
    assert cli.main(["update"]) == cli.UNREACHABLE  # conftest: PyPI never answers in tests
    assert "E701" in capsys.readouterr().err


# --------------------------------------------------------------- the notice


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(update, "_terminal", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("BOBINA_NONINTERACTIVE", raising=False)
    monkeypatch.setattr(
        update, "detect", lambda latest=None: update.Install("uv", "uv tool", ["uv"], "uv tool upgrade bobina")
    )


def test_the_notice_comes_once_a_day_at_the_end(pypi, version, terminal, capsys):
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "bobina 0.1.4 is available (you have 0.1.3): uv tool upgrade bobina" in capsys.readouterr().err
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "is available" not in capsys.readouterr().err and len(pypi) == 1  # asked today already
    state = update._state()
    state.write_text(json.dumps({"checked": time.time() - update.DAY - 5}))
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "is available" in capsys.readouterr().err and len(pypi) == 2


@pytest.mark.parametrize(
    "how",
    [["--json"], ["-q"], ["--problems", "json"], "CI", "BOBINA_NONINTERACTIVE", "pipe", "off", "dev", "mcp"],
)
def test_the_notice_never_speaks_to_agents_scripts_or_pipes(how, pypi, version, terminal, monkeypatch, capsys):
    argv = ["config", "get", "marks"]
    if how == "CI":
        monkeypatch.setenv("CI", "true")
    elif how == "BOBINA_NONINTERACTIVE":
        monkeypatch.setenv("BOBINA_NONINTERACTIVE", "1")
    elif how == "pipe":
        monkeypatch.setattr(update, "_terminal", lambda: False)
    elif how == "off":
        assert cli.main(["config", "set", "update_check", "off"]) == cli.OK
        pypi.clear()  # that command still checked: it ran before the setting was saved
        update._state().unlink(missing_ok=True)
    elif how == "dev":
        version("0.1.0.dev0")
    elif how == "mcp":
        assert not update.wanted(type("A", (), {})(), "mcp", "pretty")
        return
    else:
        argv = how + argv if how[0] == "--problems" else argv + how
    capsys.readouterr()
    cli.main(argv)
    assert "is available" not in capsys.readouterr().err
    assert pypi == []  # not even asked


def test_no_network_is_silent_and_waits_a_day(version, terminal, capsys):
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "available" not in capsys.readouterr().err and "E701" not in capsys.readouterr().err
    st = json.loads(update._state().read_text())
    assert "checked" in st and "latest" not in st  # asked (waits a day), nothing learnt


def test_an_editable_checkout_gets_no_notice(pypi, version, terminal, monkeypatch, capsys):
    monkeypatch.setattr(update, "detect", lambda latest=None: update.Install("dev", "an editable checkout"))
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "is available" not in capsys.readouterr().err


# --------------------------------------------------------------- review fixes


def test_a_check_cut_off_by_the_exit_still_waits_a_day(version, terminal, monkeypatch, capsys):
    import threading

    gate = threading.Event()
    calls = []

    def slow(timeout=update.TIMEOUT):
        calls.append(1)
        gate.wait(5)
        raise update.UpdateError("too slow")

    monkeypatch.setattr(update, "fetch", slow)
    monkeypatch.setattr(update.Check, "WAIT", 0.05)
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert cli.main(["config", "get", "marks"]) == cli.OK
    gate.set()
    assert calls == [1]  # the attempt was recorded when it started


def test_an_answer_that_came_late_tells_the_next_command(pypi, version, terminal, capsys):
    update._write({"checked": time.time(), "latest": "0.1.4"})
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "bobina 0.1.4 is available" in capsys.readouterr().err and pypi == []
    assert cli.main(["config", "get", "marks"]) == cli.OK
    assert "is available" not in capsys.readouterr().err  # said once a day


def test_any_failure_on_the_way_is_no_answer(monkeypatch):
    import http.client
    import urllib.request

    from bobina import update as real

    monkeypatch.undo()  # the real fetch, with urlopen faked
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(http.client.IncompleteRead(b""))
    )
    with pytest.raises(real.UpdateError):
        real.fetch()
    for bad in ([], {"releases": []}, {"releases": {"0.1.4": "x"}}, {"info": "x"}):
        with pytest.raises(real.UpdateError):
            real.newest(bad)


def test_help_json_names_exit_10():
    from bobina.cli import args as A

    assert A.EXIT_CODES[10].startswith("a newer release")


def test_json_command_is_a_command_and_steps_are_words(monkeypatch):
    monkeypatch.setattr(update, "_direct_url", lambda: None)
    deb = update.detect("0.1.4", prefix="/usr", module="/usr/lib/bobina/common/bobina").as_dict()
    assert deb["command"] == "" and deb["steps"].startswith("download ")
    monkeypatch.setattr(update, "_direct_url", lambda: {"url": "git+https://x/bobina", "vcs_info": {}})
    git = update.detect(prefix="/home/a/.local/share/pipx/venvs/bobina", module="/x").as_dict()
    assert git["command"] == "pipx install --force bobina" and "(" not in git["command"]


def test_homebrew_through_its_opt_symlink_and_pipx_under_any_home(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "_direct_url", lambda: None)
    keg = "/opt/homebrew/Cellar/bobina/0.1.3/libexec/lib/python3.14/site-packages/bobina"
    assert update.detect(prefix="/opt/homebrew/opt/bobina/libexec", module=keg).kind == "homebrew"
    px = tmp_path / "tools" / "px" / "venvs" / "bobina"
    px.mkdir(parents=True)
    (px / "pipx_metadata.json").write_text("{}")
    assert update.detect(prefix=str(px), module="/x").kind == "pipx"


def test_update_never_asks_a_script_with_a_controlling_terminal(pypi, version, monkeypatch, capsys):
    from test_steps import FakeTTY

    monkeypatch.setattr(update, "detect", lambda latest=None: update.Install("pipx", "pipx", ["pipx"], "pipx upgrade"))
    asked = []
    monkeypatch.setattr(cli_update, "open_tty", lambda: asked.append(1) or FakeTTY("y"))
    monkeypatch.setattr(cli_update, "_person", lambda: False)
    assert cli.main(["update"]) == cli.OK and asked == []
