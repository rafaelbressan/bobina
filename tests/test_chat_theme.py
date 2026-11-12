"""The screen colours of the chat: presets, the terminal's background, one's own colours, NO_COLOR, /screen-colors."""

import pytest

from bobina import config
from bobina.cli import chat_theme as T
from bobina.cli import main

DARK_TERM = {"COLORFGBG": "15;0"}
LIGHT_TERM = {"COLORFGBG": "0;15"}


def test_every_preset_styles_every_element():
    for name in T.THEMES:
        styles = T.build(name).styles()
        assert {"you", "ai", "dim", "frame", "status", "note", "over"} <= set(styles)
    assert "bold" in T.build("mono").styles()["you"] and not T.build("mono").color


@pytest.mark.parametrize(
    "option,cfg,env,want",
    [
        (None, {}, {}, "dark"),  # nothing known: dark
        (None, {}, LIGHT_TERM, "light"),  # the terminal says light
        (None, {}, DARK_TERM, "dark"),
        (None, {"chat_screen_colors": "contrast"}, LIGHT_TERM, "contrast"),  # config.toml over the terminal
        ("mono", {"chat_screen_colors": "contrast"}, LIGHT_TERM, "mono"),  # --screen-colors over config.toml
        (None, {"chat_screen_colors": "High-Contrast"}, {}, "contrast"),  # a synonym, any case
        (None, {"chat_theme": "contrast"}, LIGHT_TERM, "contrast"),  # the old key is read too
        (None, {"chat_theme": "contrast", "chat_screen_colors": "mono"}, {}, "mono"),  # the new one wins
    ],
)
def test_which_theme(option, cfg, env, want):
    assert T.pick(option, cfg, env).name == want


def test_a_wrong_chat_screen_colors_is_a_note_and_falls_back():
    theme = T.pick(None, {"chat_screen_colors": "neon"}, LIGHT_TERM)
    assert theme.name == "light" and "chat_screen_colors = 'neon'" in theme.notes[0] and "dark, light" in theme.notes[0]


def test_the_old_names_in_config_are_read_with_a_note():
    cfg = {"chat_theme": "light", "chat": {"colors": {"you": "#111111", "ai": "#222222"},
                                           "screen_colors": {"you": "#333333"}}}  # fmt: skip
    theme = T.pick(None, cfg, {})
    assert theme.name == "light" and theme.colors["you"] == "#333333" and theme.colors["ai"] == "#222222"
    assert "chat_theme in config.toml is now called chat_screen_colors" in theme.notes[0]
    assert any("[chat.colors] in config.toml is now called [chat.screen_colors]" in n for n in theme.notes)


def test_own_colours_override_the_preset_and_wrong_ones_fall_back():
    cfg = {"chat": {"screen_colors": {"you": "#ff8700", "ai": "bold ansired", "frame": "nope", "shadow": "#000"}}}
    theme = T.pick("light", cfg, {})
    assert theme.colors["you"] == "#ff8700" and theme.colors["ai"] == "bold ansired"
    assert theme.colors["frame"] == T.PRESETS["light"]["frame"]  # the preset's, said
    assert any("frame = 'nope': not a colour" in n for n in theme.notes)
    assert any("shadow: not a part of the chat screen" in n for n in theme.notes)
    assert "#ff8700" in theme.styles()["you"]
    assert "must be a table" in T.pick(None, {"chat": {"screen_colors": "red"}}, {}).notes[0]


def test_no_color_wins():
    cfg = {"chat_screen_colors": "contrast", "chat": {"screen_colors": {"you": "#ff8700"}}}
    theme = T.pick("dark", cfg, {"NO_COLOR": "1"})
    assert not theme.color and "#" not in " ".join(theme.styles().values())
    assert theme.styles()["you"] == "bold"  # bold stays


def test_the_colours_table_survives_a_rewrite_of_config():
    """printer add rewrites config.toml: [chat.screen_colors] and the old [chat.colors] (any table) must stay."""
    config.set_value("chat_theme", "light")
    path = config.path()
    path.write_text(
        path.read_text() + '\n[chat.colors]\nyou = "#ff8700"\nai = "bold ansired"\n'
        '\n[chat.screen_colors]\nai = "#00ff00"\n'
    )
    assert main(["printer", "add", "test", "--path", "out.bin"]) == 0
    cfg = config.load()
    assert cfg["chat"]["colors"] == {"you": "#ff8700", "ai": "bold ansired"} and cfg["chat_theme"] == "light"
    assert cfg["chat"]["screen_colors"] == {"ai": "#00ff00"}
    assert "test" in cfg["printers"]


def test_the_theme_option_and_its_hints(capsys):
    with pytest.raises(SystemExit) as e:
        main(["chat", "q?", "--screen-colors", "lihgt"])
    assert e.value.code == 1 and "did you mean light?" in capsys.readouterr().err


def test_theme_inside_the_chat(monkeypatch):
    from test_chat import Fake, LinesUI, ticket  # the same doubles as the chat tests

    from bobina.cli import chat as cli_chat

    class UI(LinesUI):
        theme = T.build("dark")
        notes: list = []

        def set_theme(self, theme):
            self.theme = theme

        def note(self, text):
            self.notes.append(text)

    ui = UI()
    args = type("A", (), {"manual": False, "questions": False, "dry_run": True, "argv": ["chat"], "printer": None,
                          "strict": False, "quiet": False})()  # fmt: skip
    from bobina import chat

    conv = chat.Conversation(Fake([]), ticket())
    s = cli_chat.Session(args, conv, None, None, ui, 80)
    s.handle("/screen-colors")
    assert "▸ dark      light text on a dark terminal  (in use)" in ui.notes[-1]
    assert "   light     dark text on a light terminal" in ui.notes[-1]
    s.handle("/screen-colors light")
    assert ui.theme.name == "light" and ui.notes[-1] == "screen colours: light (dark text on a light terminal)"
    s.handle("/theme mono")  # the old name works, with a note
    assert ui.theme.name == "mono" and "/theme is now called /screen-colors" in ui.notes
    s.handle("/screen-colors light")
    s.handle("/screen-colors neon")
    assert "no screen colours 'neon'" in ui.notes[-1] and ui.theme.name == "light"


# ------------------------------------------------------------------------------------------------ review fixes


def _session_with(ui):
    from test_chat import Fake, ticket

    from bobina import chat
    from bobina.cli import chat as cli_chat

    args = type("A", (), {"manual": False, "questions": False, "dry_run": True, "argv": ["chat"], "printer": None,
                          "strict": False, "quiet": False})()  # fmt: skip
    return cli_chat.Session(args, chat.Conversation(Fake([]), ticket()), None, None, ui, 80)


class ThemeUI:
    def __init__(self, theme):
        self.theme, self.notes = theme, []

    def set_theme(self, theme):
        self.theme = theme

    def note(self, text):
        self.notes.append(text)


def test_theme_in_the_chat_keeps_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    ui = ThemeUI(T.pick("dark", {}, off="--no-color"))
    _session_with(ui).handle("/screen-colors light")
    assert ui.theme.name == "light" and ui.theme.off == "--no-color" and not ui.theme.color
    assert ui.notes[-1] == "screen colours: light (dark text on a light terminal); --no-color: no colours"


def test_theme_in_the_chat_with_a_damaged_config():
    config.path().write_text("this is = = not toml\n")
    ui = ThemeUI(T.build("dark"))
    s = _session_with(ui)
    s.handle("/screen-colors light")
    assert ui.theme.name == "light" and "[chat.screen_colors] not read" in ui.notes[0]
    s.handle("/screen-colors")  # the chat goes on
    assert "▸ light" in ui.notes[-1]


@pytest.mark.parametrize(
    "env,flag,why",
    [({"NO_COLOR": "1"}, False, "NO_COLOR is set"), ({}, True, "--no-color"), ({"TERM": "dumb"}, False, "TERM=dumb"),
     ({"NO_COLOR": "1"}, True, "NO_COLOR is set"), ({}, False, "")],
)  # fmt: skip
def test_why_colours_are_off(env, flag, why):
    from bobina.view import colors_off

    assert colors_off(env=env, flag=flag) == why


def test_no_colour_keeps_the_attributes_of_ones_own_colours():
    cfg = {"chat": {"screen_colors": {"you": "italic #ff8700", "ai-text": "underline ansiblue", "frame": "#1a2b3c"}}}
    styles = T.pick("dark", cfg, off="NO_COLOR is set").styles()
    assert styles["you"] == "bold italic" and styles["ai-text"] == "underline" and styles["frame"] == ""
    assert "#" not in " ".join(styles.values()) and "ansi" not in " ".join(styles.values())


def test_the_text_of_each_speaker_has_its_own_element():
    assert T.build("dark").styles()["you-text"] == "#87d7d7"
    own = {"chat": {"screen_colors": {"you-text": "#ffd700", "ai-text": "#c0c0c0"}}}
    styles = T.pick("dark", own, env={}).styles()
    assert styles["you-text"] == "#ffd700" and styles["ai-text"] == "#c0c0c0" and styles["you"] == "bold #00afaf"


@pytest.mark.parametrize(
    "value,want",
    [("15;0", "dark"), ("0;15", "light"), ("0;7", "light"), ("15;default;0", "dark"), ("0;231", "light"),
     ("0;255", "light"), ("0;250", "light"), ("0;16", "dark"), ("0;232", "dark"), ("0;17", "dark"),
     ("0;bright", None), ("", None)],
)  # fmt: skip
def test_the_terminal_background(value, want):
    assert T.background({"COLORFGBG": value}) == want


def test_one_normaliser_for_theme_names(capsys):
    from bobina.cli import chat as cli_chat

    assert T.name_of(" High_Contrast ") == "contrast"
    convert = cli_chat._value("theme", T.THEMES, T.WORDS)
    assert convert(" High_Contrast ") == "contrast" and convert("LIGHT") == "light"


def test_the_descriptions_are_the_one_source():
    """What each choice looks like is written once: the chat's lists, completion, --help and docs/chat.md read it."""
    from pathlib import Path

    from bobina.chat import LOOKS
    from bobina.cli import chat as cli_chat
    from bobina.cli.args import COMMANDS, make_parser

    make_parser()
    help_text = " ".join(COMMANDS["chat"].format_help().split())
    docs = " ".join((Path(__file__).resolve().parents[1] / "docs" / "chat.md").read_text().split())
    for name, look in LOOKS.items():
        assert cli_chat.COMMANDS[f"/paper-style {name}"] == look.about and look.about in help_text
    for name, about in T.ABOUT.items():
        assert cli_chat.COMMANDS[f"/screen-colors {name}"] == about and about in help_text and about in docs
    for name in ("labels-underline", "labels-dashes", "labels-dots", "labels-outline", "labels-filled", "labels-hook"):
        assert f"`{name}`: {LOOKS[name].about}" in docs, name
