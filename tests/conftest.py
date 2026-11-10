import pytest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BOBINA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BOBINA_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BOBINA_NOW", "2026-11-05T09:49:00")
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_TIME", raising=False)
    yield tmp_path
