"""Tag combinations (AND / OR / NOT), saved searches, and tags in the OPDS search."""

from __future__ import annotations

import importlib
import re
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from server.config import (
    IssuedConfig,
    LibraryConfig,
    MonitoringConfig,
    ReaderAuthConfig,
    ScannerConfig,
    ServerConfig,
    ThumbnailConfig,
)
from server.database import init_db
from server.models import Comic, Folder
from server.opds import app
from server.tag_query import TagQuery

ATOM = "{http://www.w3.org/2005/Atom}"

# filename -> tags
LIBRARY = {
    "A.cbz": ["humour", "crime"],
    "B.cbz": ["humour", "thriller"],
    "C.cbz": ["humour", "crime", "read"],
    "D.cbz": [],
    "E.cbz": ["western"],
}


@pytest.fixture
def library(tmp_path, monkeypatch):
    library_path = tmp_path / "comics"
    library_path.mkdir()
    config = IssuedConfig(
        library=LibraryConfig(path=library_path, name="Test Library"),
        server=ServerConfig(),
        thumbnails=ThumbnailConfig(),
        scanner=ScannerConfig(),
        monitoring=MonitoringConfig(enabled=False),
        reader_auth=ReaderAuthConfig(),
    )

    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    monkeypatch.setattr("server.database.DB_PATH", db_file, raising=True)
    monkeypatch.setattr("server.database.engine", engine, raising=True)
    init_db()

    for module in (
        "reader.routes._common",
        "reader.routes.auth",
        "server.opds",
        "server.opds.middleware",
        "server.opds.routes",
    ):
        monkeypatch.setattr(importlib.import_module(module), "get_config", lambda: config)

    with Session(engine) as session:
        folder = Folder(name="Series", path="Series")
        session.add(folder)
        session.commit()
        session.refresh(folder)
        for filename in LIBRARY:
            session.add(
                Comic(
                    uuid=f"uuid-{filename}",
                    filename=filename,
                    path=f"Series/{filename}",
                    format="cbz",
                    file_size=100,
                    page_count=12,
                    file_modified_at=datetime.now(timezone.utc),
                    folder_id=folder.id,
                )
            )
        session.commit()

    with closing(sqlite3.connect(db_file)) as conn, conn:
        for filename, tags in LIBRARY.items():
            comic_id = conn.execute(
                "SELECT id FROM comics WHERE filename = ?", (filename,)
            ).fetchone()[0]
            for name in tags:
                conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
                tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
                conn.execute(
                    "INSERT INTO comic_tags (comic_id, tag_id) VALUES (?, ?)", (comic_id, tag_id)
                )

    yield db_file, TestClient(app)
    engine.dispose()


def _matches(db_file, query: TagQuery) -> list[str]:
    where, params = query.where_sql()
    with closing(sqlite3.connect(db_file)) as conn:
        rows = conn.execute(
            f"SELECT c.filename FROM comics c WHERE {where} ORDER BY c.filename", params
        ).fetchall()
    return [row[0] for row in rows]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (TagQuery.build(all=["humour"]), ["A.cbz", "B.cbz", "C.cbz"]),
        (TagQuery.build(all=["humour", "crime"]), ["A.cbz", "C.cbz"]),
        (TagQuery.build(any=["thriller", "western"]), ["B.cbz", "E.cbz"]),
        (TagQuery.build(none=["humour"]), ["D.cbz", "E.cbz"]),
        (TagQuery.build(all=["humour"], none=["read"]), ["A.cbz", "B.cbz"]),
        (TagQuery.build(all=["humour"], any=["crime", "thriller"], none=["read"]), ["A.cbz", "B.cbz"]),
        (TagQuery.build(all=["humour", "missing"]), []),
        (TagQuery.build(none=["missing"]), ["A.cbz", "B.cbz", "C.cbz", "D.cbz", "E.cbz"]),
        (TagQuery.build(), []),
    ],
    ids=[
        "and-one", "and-two", "or", "not-only", "and-not", "and-or-not",
        "and-unknown-tag", "not-unknown-tag", "empty",
    ],
)
def test_tag_query_matches(library, query, expected):
    db_file, _ = library
    assert _matches(db_file, query) == expected


def test_build_strips_blanks_and_duplicates():
    query = TagQuery.build(all=[" humour ", "humour", ""], any=None, none=["  "])
    assert query == TagQuery(all=["humour"], any=[], none=[])


def test_a_tag_keeps_one_state_like_on_the_tags_page():
    query = TagQuery.build(all=["x"], any=["x", "y"], none=["x", "y", "z"])
    assert query == TagQuery(all=["x"], any=["y"], none=["z"])


@pytest.mark.parametrize("stored", ["{not json", "[1, 2]", ""])
def test_unreadable_criteria_match_nothing(stored):
    assert TagQuery.from_json(stored).is_empty()


def test_editing_a_search_keeps_a_deleted_tag(library):
    _, client = library

    page = client.get("/reader/tags?all=crime&all=gone")

    states = dict(re.findall(r'data-tag-name="([^"]+)" data-state="([^"]*)"', page.text))
    assert states["gone"] == "all"


def test_describe_and_round_trips():
    query = TagQuery.build(all=["humour"], any=["crime", "thriller"], none=["read"])
    assert query.describe() == "humour AND (crime OR thriller) NOT read"
    assert TagQuery.build(any=["crime", "thriller"]).describe() == "crime OR thriller"
    assert TagQuery.build(none=["read", "lent"]).describe() == "NOT read NOT lent"
    # Without the parentheses this would read as: crime OR (thriller NOT read).
    assert TagQuery.build(any=["crime", "thriller"], none=["read"]).describe() == "(crime OR thriller) NOT read"
    assert TagQuery.from_json(query.to_json()) == query
    assert query.query_string() == "all=humour&any=crime&any=thriller&none=read"


def test_tag_search_page(library):
    _, client = library

    page = client.get("/reader/tag-search?all=humour&any=crime&any=thriller&none=read")

    assert page.status_code == 200
    assert "A.cbz" in page.text and "B.cbz" in page.text
    assert "C.cbz" not in page.text and "D.cbz" not in page.text
    assert "humour AND (crime OR thriller) NOT read" in page.text
    # The edit link brings the combination back to the tags page.
    assert "/reader/tags?all=humour&amp;any=crime&amp;any=thriller&amp;none=read" in page.text


def test_tags_page_preselects_the_combination(library):
    _, client = library

    page = client.get("/reader/tags?all=humour&none=read")

    assert page.status_code == 200
    states = dict(re.findall(r'data-tag-name="([^"]+)" data-state="([^"]*)"', page.text))
    assert states == {"crime": "", "humour": "all", "read": "none", "thriller": "", "western": ""}


def test_save_list_replace_and_delete_a_search(library):
    _, client = library

    created = client.post(
        "/reader/api/saved-searches", json={"name": "Crime to read", "all": ["crime"], "none": ["read"]}
    )
    assert created.status_code == 200
    search_id = created.json()["id"]

    page = client.get("/reader/tags")
    assert "Crime to read" in page.text
    assert f'/reader/tag-search?all=crime&amp;none=read' in page.text

    # Same name: the criteria are replaced, no second row.
    replaced = client.post("/reader/api/saved-searches", json={"name": "Crime to read", "any": ["western"]})
    assert replaced.json()["id"] == search_id
    feed = ET.fromstring(client.get(f"/opds/saved-searches/{search_id}").content)
    assert [e.findtext(f"{ATOM}title") for e in feed.iter(f"{ATOM}entry")] == ["E.cbz"]

    assert client.delete(f"/reader/api/saved-searches/{search_id}").status_code == 200
    assert client.delete(f"/reader/api/saved-searches/{search_id}").status_code == 404
    assert "Crime to read" not in client.get("/reader/tags").text


@pytest.mark.parametrize(
    "body",
    [{"name": "  ", "all": ["crime"]}, {"name": "Nothing", "all": [" "]}],
    ids=["blank-name", "no-tag"],
)
def test_save_rejects_an_empty_search(library, body):
    _, client = library
    assert client.post("/reader/api/saved-searches", json=body).status_code == 422


def test_opds_lists_saved_searches(library):
    _, client = library

    root = ET.fromstring(client.get("/opds/").content)
    assert "Saved searches" not in [e.findtext(f"{ATOM}title") for e in root.iter(f"{ATOM}entry")]

    client.post("/reader/api/saved-searches", json={"name": "Funny & read", "all": ["humour", "read"]})

    root = ET.fromstring(client.get("/opds/").content)
    assert "Saved searches" in [e.findtext(f"{ATOM}title") for e in root.iter(f"{ATOM}entry")]

    listing = ET.fromstring(client.get("/opds/saved-searches").content)
    (entry,) = listing.iter(f"{ATOM}entry")
    assert entry.findtext(f"{ATOM}title") == "Funny & read"
    href = entry.find(f"{ATOM}link").get("href")

    feed = ET.fromstring(client.get(href).content)
    assert feed.findtext(f"{ATOM}title") == "Funny & read"
    assert [e.findtext(f"{ATOM}title") for e in feed.iter(f"{ATOM}entry")] == ["C.cbz"]

    assert client.get("/opds/saved-searches/999").status_code == 404


def test_opds_search_finds_tags(library):
    _, client = library

    feed = ET.fromstring(client.get("/opds/search?q=thrill").content)

    assert [e.findtext(f"{ATOM}title") for e in feed.iter(f"{ATOM}entry")] == ["B.cbz"]
