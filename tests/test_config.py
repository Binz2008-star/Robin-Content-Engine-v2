from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import config as config_module  # noqa: E402


def _reload_config() -> None:
    """APP_ROOT is a module-level constant computed at import time (and
    the Settings env_file path is bound to it at class definition time),
    so honoring a ROBIN_APP_ROOT override in a test requires reloading
    the module. Every test that reloads restores the module to its real
    defaults in a finally block, so the module state never leaks."""
    importlib.reload(config_module)


def test_resolve_app_root_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ROBIN_APP_ROOT", str(tmp_path / "override dir"))
    assert config_module.resolve_app_root() == (tmp_path / "override dir").resolve()


def test_resolve_app_root_defaults_to_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBIN_APP_ROOT", raising=False)
    assert config_module.resolve_app_root() == Path(config_module.__file__).resolve().parents[2]


def test_settings_loads_env_file_from_app_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The .env file is resolved against the canonical APP_ROOT (never the
    process's current working directory - the bug the scheduled-task
    launcher used to hit), and Settings reads it from there."""
    monkeypatch.setenv("ROBIN_APP_ROOT", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://from-env-file\nDEEPSEEK_API_KEY=file-key\n",
        encoding="utf-8",
    )
    try:
        _reload_config()
        settings = config_module.Settings()
        assert settings.database_url == "postgresql://from-env-file"
        assert settings.deepseek_api_key == "file-key"
        # the file was found at APP_ROOT/.env, not at the cwd
        assert config_module.Settings.model_config.get("env_file") == str(
            tmp_path / ".env"
        ) or config_module.Settings.model_config["env_file"] == str(tmp_path / ".env")
    finally:
        monkeypatch.delenv("ROBIN_APP_ROOT", raising=False)
        _reload_config()


def test_settings_anchors_relative_paths_to_app_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Relative configured paths (work dir, OAuth credential files,
    capture source) are anchored to APP_ROOT instead of the process cwd,
    so a launcher running from anywhere cannot silently redirect runtime
    files or credentials to the wrong location."""
    monkeypatch.setenv("ROBIN_APP_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://anchored")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "anchored-key")
    monkeypatch.setenv("CAPTURE_SOURCE_DIR", "captures")
    try:
        _reload_config()
        settings = config_module.Settings()
        assert settings.work_dir == (tmp_path / "work").resolve()
        assert settings.youtube_client_secret_file == (tmp_path / "client_secret.json").resolve()
        assert settings.youtube_token_file == (tmp_path / "token.json").resolve()
        assert settings.capture_source_dir == (tmp_path / "captures").resolve()
        assert all(
            path.is_absolute()
            for path in (
                settings.work_dir,
                settings.youtube_client_secret_file,
                settings.youtube_token_file,
                settings.capture_source_dir,
            )
        )
    finally:
        monkeypatch.delenv("ROBIN_APP_ROOT", raising=False)
        _reload_config()


def test_settings_leaves_absolute_paths_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    abs_capture = tmp_path / "abs-captures"
    monkeypatch.setenv("ROBIN_APP_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://abs")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "abs-key")
    monkeypatch.setenv("CAPTURE_SOURCE_DIR", str(abs_capture))
    try:
        _reload_config()
        settings = config_module.Settings()
        assert settings.capture_source_dir == abs_capture.resolve()
    finally:
        monkeypatch.delenv("ROBIN_APP_ROOT", raising=False)
        _reload_config()