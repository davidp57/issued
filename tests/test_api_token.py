"""Token access to the reader JSON API through the X-Issued-Token header."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from server.config import (
    API_TOKEN_ENV_VAR,
    IssuedConfig,
    LibraryConfig,
    MonitoringConfig,
    ReaderAuthConfig,
    ScannerConfig,
    ServerConfig,
    ThumbnailConfig,
    load_config,
)
from server.database import init_db
from server.opds import app

TOKEN = "t" * 48


@pytest.fixture
def reader(tmp_path, monkeypatch):
    library_path = tmp_path / "comics"
    library_path.mkdir()
    config = IssuedConfig(
        library=LibraryConfig(path=library_path, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(enabled=False),
        reader_auth=ReaderAuthConfig(user="reader", password="secret", api_token=TOKEN),
    )

    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    init_db()

    for module in ("reader.routes._common", "reader.routes.auth", "server.opds.middleware"):
        monkeypatch.setattr(importlib.import_module(module), "get_config", lambda: config)

    return config, TestClient(app)


def test_valid_token_opens_the_api(reader):
    _, client = reader

    response = client.get(
        "/reader/api/tags", headers={"X-Issued-Token": TOKEN}, follow_redirects=False
    )

    assert response.status_code == 200
    assert response.json() == {"tags": []}


def test_invalid_token_is_rejected_with_json(reader):
    _, client = reader

    response = client.get(
        "/reader/api/tags", headers={"X-Issued-Token": "x" * 48}, follow_redirects=False
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API token"}


def test_token_does_not_open_html_pages(reader):
    _, client = reader

    response = client.get(
        "/reader/", headers={"X-Issued-Token": TOKEN}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/reader/login")


def test_without_header_the_api_still_redirects_to_login(reader):
    _, client = reader

    response = client.get("/reader/api/tags", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("/reader/login")


def test_too_short_token_is_ignored(reader):
    config, client = reader
    short = "s" * 31
    config.reader_auth = ReaderAuthConfig(user="reader", password="secret", api_token=short)

    response = client.get(
        "/reader/api/tags", headers={"X-Issued-Token": short}, follow_redirects=False
    )

    assert config.reader_auth.api_token_too_short
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API token"}


def test_without_reader_auth_the_header_changes_nothing(reader):
    config, client = reader
    config.reader_auth = ReaderAuthConfig(api_token=TOKEN)

    wrong = client.get(
        "/reader/api/tags", headers={"X-Issued-Token": "x" * 48}, follow_redirects=False
    )
    page = client.get("/reader/", headers={"X-Issued-Token": TOKEN}, follow_redirects=False)

    assert wrong.status_code == 200
    assert page.status_code == 200


def test_token_never_reaches_the_logs(reader, caplog, monkeypatch):
    _, client = reader
    # The request journal logs only the first request of the process.
    monkeypatch.setattr(app.state, "logged_first_request", False, raising=False)

    with caplog.at_level(logging.DEBUG):
        client.get("/reader/api/tags", headers={"X-Issued-Token": TOKEN})
        client.get("/reader/api/tags", headers={"X-Issued-Token": "x" * 48})

    assert "client_connected" in caplog.text
    assert TOKEN not in caplog.text
    assert "x" * 48 not in caplog.text


def _write_config(tmp_path: Path, reader_section: str) -> Path:
    path = tmp_path / "config.ini"
    path.write_text(f"[reader]\n{reader_section}", encoding="utf-8")
    return path


def test_token_is_read_from_config_ini(tmp_path, monkeypatch):
    monkeypatch.delenv(API_TOKEN_ENV_VAR, raising=False)

    config = load_config(_write_config(tmp_path, f"api_token = {TOKEN}\n"))

    assert config.reader_auth.active_api_token == TOKEN


def test_environment_variable_wins_over_config_ini(tmp_path, monkeypatch):
    from_env = "e" * 40
    monkeypatch.setenv(API_TOKEN_ENV_VAR, from_env)

    config = load_config(_write_config(tmp_path, f"api_token = {TOKEN}\n"))

    assert config.reader_auth.active_api_token == from_env


def test_percent_in_config_ini_token_is_kept(tmp_path, monkeypatch):
    monkeypatch.delenv(API_TOKEN_ENV_VAR, raising=False)
    token = "%" + TOKEN

    config = load_config(_write_config(tmp_path, f"api_token = {token}\n"))

    assert config.reader_auth.active_api_token == token


def test_token_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(API_TOKEN_ENV_VAR, raising=False)

    config = load_config(_write_config(tmp_path, ""))

    assert config.reader_auth.active_api_token == ""
    assert not config.reader_auth.api_token_too_short
