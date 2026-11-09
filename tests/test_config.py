from pathlib import Path

from bambu_mcp import config


def test_env_file_prefers_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("BAMBU_ENV_FILE", str(tmp_path / "x.env"))
    assert config._env_file() == tmp_path / "x.env"


def test_env_file_uses_home_file_when_present(monkeypatch, tmp_path):
    monkeypatch.delenv("BAMBU_ENV_FILE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".bambu-mcp.env").write_text("BAMBU_HOST=1.2.3.4\n")
    assert config._env_file() == tmp_path / ".bambu-mcp.env"


def test_env_file_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.setenv("BAMBU_ENV_FILE", "")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert config._env_file() == Path(".env")
