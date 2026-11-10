from bobina.engine import build


def test_job_starts_with_init_and_top_margin():
    data = build("hi").data
    assert data.startswith(b"\x1b@\x1bJ\x18")


def test_utf8_text_and_styles():
    data = build("**Olá** ação").data
    assert "Olá".encode() in data and "ação".encode() in data
    assert b"\x1bE\x01" in data


def test_line_spacing_set_explicitly():
    data = build("a\n\n# B").data
    assert b"\x1b3\x1e" in data  # 24 + 6
    assert b"\x1b3\x36" in data  # 48 + 6 for 2x2


def test_qr_native_command():
    data = build("```qr\nhttps://example.com\n```").data
    assert b"\x1d(k\x03\x001C\x04" in data and b"https://example.com" in data


def test_never_sends_esc_m_1():
    assert b"\x1bM\x01" not in build("# a\n\ntext *it*").data


def test_raster_rows_are_full_width():
    data = build("--- {.double}").data
    assert b"\x1dv0\x000\x00" in data  # 48 bytes per row
