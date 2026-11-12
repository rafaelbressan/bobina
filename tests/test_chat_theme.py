"""The chat screen's colours: presets, the terminal's background, one's own colours, NO_COLOR, /theme."""

import pytest

from bobina import config
from bobina.cli import chat_theme as T
from bobina.cli import main

DARK_TERM = {"COLORFGBG": "15;0"}
LIGHT_TERM = {"COLORFGBG": "0;15"}


def test_every_preset_styles_every_element():
    for name in T.THEMES:
        styles = T.build(name, env={}).styles()
        assert {"you", "ai", "dim", "frame", "status", "note", "over"} <= set(styles)
    assert "bold" in T.build("mono", env={}).styles()["you"] and not T.build("mono", env={}).color


@pytest.mark.parametrize(
    "option,cfg,env,want",
    [
        (None, {}, {}, "dark"),  # nothing known: dark
        (None, {}, LIGHT_TERM, "light"),  # the terminal says light
        (None, {}, DARK_TERM, "dark"),
        (None, {"chat_theme": "contrast"}, LIGHT_TERM, "contrast"),  # config.toml over the terminal
        ("mono", {"chat_theme": "contrast"}, LIGHT_TERM, "mono"),  # --theme over config.toml
        (None, {"chat_theme": "High-Contrast"}, {}, "contrast"),  # a synonym, any case
    ],
)
def test_which_theme(option, cfg, env, want):
    assert T.pick(option, cfg, env).name == want


def test_a_wrong_chat_theme_is_a_note_and_falls_back():
    theme = T.pick(None, {"chat_theme": "neon"}, LIGHT_TERM)
    assert theme.name == "light" and "chat_theme = 'neon'" in theme.notes[0] and "dark, light" in theme.notes[0]


def test_own_colours_override_the_preset_and_wrong_ones_fall_back():
    cfg = {"chat": {"colors": {"you": "#ff8700", "ai": "bold ansired", "frame": "nope", "shadow": "#000"}}}
    theme = T.pick("light", cfg, {})
    assert theme.colors["you"] == "#ff8700" and theme.colors["ai"] == "bold ansired"
    assert theme.colors["frame"] == T.PRESETS["light"]["frame"]  # the preset's, said
    assert any("frame = 'nope': not a colour" in n for n in theme.notes)
    assert any("shadow: not an element" in n for n in theme.notes)
    assert "#ff8700" in theme.styles()["you"]
    assert "must be a table" in T.pick(None, {"chat": {"colors": "red"}}, {}).notes[0]


def test_no_color_wins():
    cfg = {"chat_theme": "contrast", "chat": {"colors": {"you": "#ff8700"}}}
    theme = T.pick("dark", cfg, {"NO_COLOR": "1"})
    assert not theme.color and "#" not in " ".join(theme.styles().values())
    assert theme.styles()["you"] == "bold"  # bold stays


def test_the_colours_table_survives_a_rewrite_of_config():
    """printer add rewrites config.toml: [chat.colors] (and any other table) must stay."""
    config.set_value("chat_theme", "light")
    path = config.path()
    path.write_text(path.read_text() + '\n[chat.colors]\nyou = "#ff8700"\nai = "bold ansired"\n')
    assert main(["printer", "add", "test", "--path", "out.bin"]) == 0
    cfg = config.load()
    assert cfg["chat"]["colors"] == {"you": "#ff8700", "ai": "bold ansired"} and cfg["chat_theme"] == "light"
    assert "test" in cfg["printers"]


def test_the_theme_option_and_its_hints(capsys):
    with pytest.raises(SystemExit) as e:
        main(["chat", "q?", "--theme", "lihgt"])
    assert e.value.code == 1 and "did you mean light?" in capsys.readouterr().err


def test_theme_inside_the_chat(monkeypatch):
    from test_chat import Fake, LinesUI, ticket  # the same doubles as the chat tests

    from bobina.cli import chat as cli_chat

    class UI(LinesUI):
        theme = T.build("dark", env={})
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
    s.handle("/theme")
    assert "dark (in use)" in ui.notes[-1] and "light" in ui.notes[-1]
    s.handle("/theme light")
    assert ui.theme.name == "light" and ui.notes[-1].startswith("theme light")
    s.handle("/theme neon")
    assert "no theme 'neon'" in ui.notes[-1] and ui.theme.name == "light"
