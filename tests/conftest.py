import pytest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BOBINA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BOBINA_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BOBINA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOBINA_NOW", "2026-11-05T09:49:00")
    monkeypatch.setenv("BOBINA_MEMORY_LIMIT", "0")  # --sandbox's ceiling would stay on the test process itself
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_TIME", raising=False)
    # a machine whose locale was already chosen (the first run infers pt-BR from the zone: tests/test_locale.py)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text('locale = "en-US"\n')
    from bobina import scriptfonts

    def no_network(url, size):  # fonts for other scripts are never downloaded in tests (tests/test_scriptfonts.py)
        raise scriptfonts.FontDownloadError("no network in tests")

    monkeypatch.setattr(scriptfonts, "fetch", no_network)
    scriptfonts._FAILED.clear()
    yield tmp_path
