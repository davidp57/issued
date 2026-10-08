"""Deleting comics from the web reader: delete, trash, traces, restore."""

from __future__ import annotations

import dataclasses
import importlib
import io
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import create_engine

from server import scanner
from server.config import DeletionConfig, load_config
from server.database import init_db
from server.opds import app
from tests.test_scanner import _create_minimal_cbz, _make_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A library with one comic, scanned, and the reader app wired to it."""
    db_file = tmp_path / "library.db"
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr(
        "server.database.engine",
        create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False}),
        raising=True,
    )
    monkeypatch.setattr("server.config.DATA_DIR", tmp_path / "data", raising=True)
    init_db()

    library = tmp_path / "comics"
    (library / "Marvel" / "XMen").mkdir(parents=True)
    comic = library / "Marvel" / "XMen" / "X-Men 001.cbz"
    _create_minimal_cbz(comic)
    trash = tmp_path / "trash"
    trash.mkdir()

    holder = {"config": _make_config(library)}

    def set_mode(mode: str, trash_path: Path | None = trash) -> None:
        holder["config"] = dataclasses.replace(
            holder["config"], deletion=DeletionConfig(mode=mode, trash_path=trash_path)
        )

    get_config = lambda: holder["config"]  # noqa: E731
    monkeypatch.setattr("server.opds.get_config", get_config)
    monkeypatch.setattr(importlib.import_module("reader.routes._common"), "get_config", get_config)
    monkeypatch.setattr(importlib.import_module("reader.routes.api_trash"), "get_config", get_config)

    scanner.scan_library(holder["config"])

    class Env:
        pass

    e = Env()
    e.db_file, e.library, e.comic, e.trash = db_file, library, comic, trash
    e.set_mode = set_mode
    e.config = lambda: holder["config"]
    e.client = TestClient(app)
    return e


def _rows(db_file: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _uuid(env) -> str:
    return _rows(env.db_file, "SELECT uuid FROM comics")[0][0]


def _different_cbz(path: Path) -> None:
    _create_minimal_cbz(path)
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("page002.txt", "not the same file")


def _create_cbz_with_page_name(path: Path, page_name: str) -> None:
    """Like ``_create_minimal_cbz``, with another name for its single page."""
    img = Image.new("RGB", (10, 10), color="red")
    data = io.BytesIO()
    img.save(data, format="PNG")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(page_name, data.getvalue())


# --- Config ---


def _write_config(tmp_path: Path, deletion: str) -> Path:
    library = tmp_path / "lib"
    library.mkdir(exist_ok=True)
    path = tmp_path / "config.ini"
    path.write_text(f"[library]\npath = {library}\n\n[deletion]\n{deletion}\n", encoding="utf-8")
    return path


def test_deletion_is_off_by_default(tmp_path):
    config = load_config(_write_config(tmp_path, ""))

    assert config.deletion.mode == "off"
    assert not config.deletion.enabled


def test_trash_mode_requires_a_trash_path(tmp_path):
    with pytest.raises(ValueError, match="trash_path"):
        load_config(_write_config(tmp_path, "mode = trash"))


def test_trash_path_inside_the_library_is_refused(tmp_path):
    inside = tmp_path / "lib" / ".trash"
    with pytest.raises(ValueError, match="outside the library"):
        load_config(_write_config(tmp_path, f"mode = trash\ntrash_path = {inside}"))


def test_unknown_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        load_config(_write_config(tmp_path, "mode = shred"))


# --- Delete action ---


def test_delete_is_refused_when_off(env):
    response = env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    assert response.status_code == 403
    assert env.comic.exists()


def test_delete_button_and_trash_link_follow_the_mode(env):
    page = env.client.get("/reader/recent").text
    assert 'id="comic-info-delete"' not in page
    assert ">Trash</a>" not in page

    env.set_mode("trash")
    page = env.client.get("/reader/recent").text
    assert 'id="comic-info-delete" data-mode="trash"' in page
    assert ">Trash</a>" in page


def test_delete_mode_removes_the_file_and_keeps_a_trace(env):
    env.set_mode("delete")

    response = env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    assert response.status_code == 200
    assert response.json()["mode"] == "delete"
    assert not env.comic.exists()
    assert _rows(env.db_file, "SELECT * FROM comics") == []
    assert _rows(env.db_file, "SELECT filename, path, mode, trash_path FROM deleted_comics") == [
        ("X-Men 001.cbz", "Marvel/XMen/X-Men 001.cbz", "delete", None)
    ]


def test_trash_mode_moves_the_file_keeping_its_folders(env):
    env.set_mode("trash")

    response = env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    assert response.status_code == 200
    assert not env.comic.exists()
    assert (env.trash / "Marvel" / "XMen" / "X-Men 001.cbz").is_file()
    assert _rows(env.db_file, "SELECT * FROM comics") == []
    assert _rows(env.db_file, "SELECT trash_path FROM deleted_comics") == [
        ("Marvel/XMen/X-Men 001.cbz",)
    ]


def test_trashing_twice_the_same_path_keeps_both_files(env):
    env.set_mode("trash")
    original = env.comic.read_bytes()
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    _different_cbz(env.comic)
    scanner.scan_library(env.config())

    env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    folder = env.trash / "Marvel" / "XMen"
    assert (folder / "X-Men 001.cbz").read_bytes() == original
    assert (folder / "X-Men 001 (2).cbz").is_file()


def test_missing_trash_folder_leaves_everything_untouched(env, tmp_path):
    env.set_mode("trash", trash_path=tmp_path / "not-mounted")

    response = env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    assert response.status_code == 503
    assert env.comic.exists()
    assert not (tmp_path / "not-mounted").exists()
    assert len(_rows(env.db_file, "SELECT * FROM comics")) == 1
    assert _rows(env.db_file, "SELECT * FROM deleted_comics") == []


def test_failed_removal_rolls_the_database_back(env, monkeypatch):
    env.set_mode("delete")

    def refuse(self, *args, **kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(Path, "unlink", refuse)
    response = env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    assert response.status_code == 500
    assert "read-only" in response.json()["detail"]
    assert env.comic.exists()
    assert len(_rows(env.db_file, "SELECT * FROM comics")) == 1
    assert _rows(env.db_file, "SELECT * FROM deleted_comics") == []


def test_trashed_file_comes_back_when_the_database_write_fails(env, monkeypatch):
    env.set_mode("trash")

    def locked(self):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("server.repository.Repository.commit", locked)
    response = env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    assert response.status_code == 500
    assert env.comic.is_file()
    assert not (env.trash / "Marvel" / "XMen" / "X-Men 001.cbz").exists()
    assert len(_rows(env.db_file, "SELECT * FROM comics")) == 1
    assert _rows(env.db_file, "SELECT * FROM deleted_comics") == []


# --- The scanner and the traces ---


def test_identical_file_dropped_again_is_not_imported(env, tmp_path):
    env.set_mode("delete")
    copy = tmp_path / "copy.cbz"
    copy.write_bytes(env.comic.read_bytes())
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")

    # Back under the same name, even in another folder.
    elsewhere = env.library / "Other" / "X-Men 001.cbz"
    elsewhere.parent.mkdir()
    copy.replace(elsewhere)
    scanner.scan_library(env.config())

    assert _rows(env.db_file, "SELECT * FROM comics") == []
    assert _rows(env.db_file, "SELECT conflict_path FROM deleted_comics") == [(None,)]


def test_monitor_scan_skips_a_deleted_comic(env, tmp_path):
    env.set_mode("delete")
    copy = tmp_path / "copy.cbz"
    copy.write_bytes(env.comic.read_bytes())
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    copy.replace(env.comic)

    scanner.scan_file(env.comic, env.config())

    assert _rows(env.db_file, "SELECT * FROM comics") == []


def test_other_content_under_a_deleted_name_is_imported_and_flagged(env):
    env.set_mode("delete")
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    _different_cbz(env.comic)

    scanner.scan_library(env.config())

    assert len(_rows(env.db_file, "SELECT * FROM comics")) == 1
    assert _rows(env.db_file, "SELECT conflict_path FROM deleted_comics") == [
        ("Marvel/XMen/X-Men 001.cbz",)
    ]
    page = env.client.get("/reader/trash").text
    assert "A different file with this name was imported" in page


def test_same_size_but_other_content_is_imported(env):
    env.set_mode("delete")
    size = env.comic.stat().st_size
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    _create_cbz_with_page_name(env.comic, "page002.png")
    assert env.comic.stat().st_size == size  # reaches the hash comparison

    scanner.scan_library(env.config())

    assert len(_rows(env.db_file, "SELECT * FROM comics")) == 1
    assert _rows(env.db_file, "SELECT conflict_path FROM deleted_comics") == [
        ("Marvel/XMen/X-Men 001.cbz",)
    ]


# --- Trash page ---


def test_trash_page_is_hidden_when_off(env):
    assert env.client.get("/reader/trash").status_code == 403


def test_restore_puts_the_comic_back(env):
    env.set_mode("trash")
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    trace_id = _rows(env.db_file, "SELECT id FROM deleted_comics")[0][0]
    assert "X-Men 001.cbz" in env.client.get("/reader/trash").text

    response = env.client.post(f"/reader/api/trash/{trace_id}/restore")

    assert response.status_code == 200
    assert env.comic.is_file()
    assert not (env.trash / "Marvel" / "XMen" / "X-Men 001.cbz").exists()
    assert _rows(env.db_file, "SELECT path FROM comics") == [("Marvel/XMen/X-Men 001.cbz",)]
    assert _rows(env.db_file, "SELECT * FROM deleted_comics") == []


def test_restore_does_not_overwrite_a_file_in_place(env):
    env.set_mode("trash")
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    trace_id = _rows(env.db_file, "SELECT id FROM deleted_comics")[0][0]
    _different_cbz(env.comic)
    replacement = env.comic.read_bytes()

    response = env.client.post(f"/reader/api/trash/{trace_id}/restore")

    assert response.status_code == 409
    assert env.comic.read_bytes() == replacement
    assert (env.trash / "Marvel" / "XMen" / "X-Men 001.cbz").is_file()


def test_failed_restore_keeps_the_trace(env, monkeypatch):
    env.set_mode("trash")
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    trace_id = _rows(env.db_file, "SELECT id FROM deleted_comics")[0][0]

    def full_disk(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr("server.deletion.shutil.move", full_disk)
    response = env.client.post(f"/reader/api/trash/{trace_id}/restore")

    assert response.status_code == 500
    assert not env.comic.exists()
    assert (env.trash / "Marvel" / "XMen" / "X-Men 001.cbz").is_file()
    assert _rows(env.db_file, "SELECT id, path, trash_path FROM deleted_comics") == [
        (trace_id, "Marvel/XMen/X-Men 001.cbz", "Marvel/XMen/X-Men 001.cbz")
    ]


def test_a_deleted_comic_cannot_be_restored(env):
    env.set_mode("delete")
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    trace_id = _rows(env.db_file, "SELECT id FROM deleted_comics")[0][0]

    assert env.client.post(f"/reader/api/trash/{trace_id}/restore").status_code == 409


def test_forget_lets_the_file_be_imported_again(env, tmp_path):
    env.set_mode("delete")
    copy = tmp_path / "copy.cbz"
    copy.write_bytes(env.comic.read_bytes())
    env.client.delete(f"/reader/api/comic/{_uuid(env)}")
    trace_id = _rows(env.db_file, "SELECT id FROM deleted_comics")[0][0]

    assert env.client.delete(f"/reader/api/trash/{trace_id}").status_code == 200
    copy.replace(env.comic)
    scanner.scan_library(env.config())

    assert len(_rows(env.db_file, "SELECT * FROM comics")) == 1
    assert _rows(env.db_file, "SELECT * FROM deleted_comics") == []
