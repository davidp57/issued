"""Delete comics from the library, keep a trace, and restore them from the trash.

A deleted comic leaves a ``DeletedComic`` trace. The scanner asks
``check_deleted`` before importing a new file: a file with the same name and
the same content is skipped, so a sync tool that drops the file again does not
bring the comic back.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from .config import IssuedConfig
from .database import get_engine
from .logging_config import get_logger
from .models import DeletedComic
from .path_utils import to_absolute, to_relative
from .repository import Repository
from .utils import delete_thumbnails

logger = get_logger(__name__)

_HASH_CHUNK = 1024 * 1024


class DeletionError(RuntimeError):
    """The comic could not be deleted or restored; nothing was changed."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DeletedInfo:
    filename: str
    mode: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _free_trash_target(trash_root: Path, rel_path: str) -> Path:
    """Return where to put the file in the trash, without overwriting anything."""
    target = trash_root / rel_path
    counter = 2
    while target.exists():
        original = trash_root / rel_path
        target = original.with_name(f"{original.stem} ({counter}){original.suffix}")
        counter += 1
    return target


def delete_comic(comic_uuid: str, config: IssuedConfig) -> DeletedInfo:
    """Delete or trash one comic, as ``config.deletion.mode`` says.

    The file is removed first, outside any transaction: a move to a trash on
    another volume is a full copy, and holding the SQLite write lock that long
    would make every other writer time out. The database is updated after,
    in one short transaction. If that fails, a trashed file is moved back; a
    deleted file is gone, and the next scan drops its row.
    """
    mode = config.deletion.mode
    if mode not in ("delete", "trash"):
        raise DeletionError("Deletion is disabled", status_code=403)

    library_root = config.library_path.resolve()
    trash_root: Optional[Path] = None
    if mode == "trash":
        trash_root = config.deletion.trash_path
        # A missing mount point must not be recreated inside the container,
        # where the trashed files would vanish with it.
        if trash_root is None or not trash_root.is_dir():
            raise DeletionError(f"Trash folder not found: {trash_root}", status_code=503)

    with Session(get_engine()) as session:
        comic = Repository(session, library_root).get_comic_by_uuid(comic_uuid)
        if comic is None:
            raise DeletionError("Comic not found", status_code=404)
        filename, rel_path = comic.filename, comic.path

    source = to_absolute(rel_path, library_root)
    if not source.is_file():
        raise DeletionError(f"File not found on disk: {rel_path}", status_code=404)

    trace = DeletedComic(
        filename=filename,
        path=rel_path,
        file_size=source.stat().st_size,
        sha256=file_sha256(source),
        mode=mode,
    )
    target: Optional[Path] = None
    if trash_root is not None:
        target = _free_trash_target(trash_root, rel_path)
        trace.trash_path = target.relative_to(trash_root).as_posix()

    try:
        if target is None:
            source.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            _move(source, target)
    except OSError as exc:
        raise DeletionError(f"Could not remove {filename}: {exc}") from exc

    try:
        with Session(get_engine()) as session:
            repo = Repository(session, library_root)
            session.add(trace)
            deleted_uuids = repo.delete_comic_by_path(source)
            repo.commit()
    except Exception as exc:
        if target is not None:
            _move(target, source)
            raise DeletionError(f"Could not record the deletion of {filename}: {exc}") from exc
        logger.error(f"✗ Deleted {rel_path} but could not record it: {exc}")
        raise DeletionError(
            f"{filename} was deleted from disk, but the database could not be updated: {exc}"
        ) from exc

    delete_thumbnails(deleted_uuids, config.thumbnails_dir)
    verb = "Deleted" if mode == "delete" else "Trashed"
    logger.info(f"[-] {verb}: {rel_path}")
    return DeletedInfo(filename=filename, mode=mode)


def _move(source: Path, target: Path) -> None:
    """Move a file, possibly across volumes, leaving no partial copy behind."""
    try:
        shutil.move(str(source), str(target))
    except OSError:
        # shutil.move copies then unlinks across volumes: if the source is
        # still there, the copy is incomplete or unwanted.
        if source.exists() and target.exists():
            target.unlink(missing_ok=True)
        raise


def check_deleted(path: Path, file_size: int, session: Session, library_root: Path) -> bool:
    """Return True if ``path`` is a deleted comic that must not be imported.

    The file is hashed only when a trace with the same name and size exists.
    A file with a known name but other content is imported, and every trace
    with that name records it as a conflict.
    """
    traces = session.exec(
        select(DeletedComic).where(DeletedComic.filename == path.name)
    ).all()
    if not traces:
        return False

    if any(t.file_size == file_size for t in traces):
        digest = file_sha256(path)
        if any(t.sha256 == digest for t in traces):
            logger.debug(f"Skipped deleted comic: {path.name}")
            return True

    rel_path = to_relative(path, library_root)
    now = datetime.now(timezone.utc)
    for trace in traces:
        trace.conflict_path = rel_path
        trace.conflict_at = now
        session.add(trace)
    logger.warning(
        f"[!] {rel_path} has the name of a deleted comic but other content; imported"
    )
    return False


def list_deleted() -> list[DeletedComic]:
    with Session(get_engine()) as session:
        return list(
            session.exec(select(DeletedComic).order_by(DeletedComic.deleted_at.desc())).all()
        )


def forget(trace_id: int) -> None:
    """Drop a trace: a file with that name will be imported again."""
    with Session(get_engine()) as session:
        trace = session.get(DeletedComic, trace_id)
        if trace is None:
            raise DeletionError("Trace not found", status_code=404)
        session.delete(trace)
        session.commit()


def restore(trace_id: int, config: IssuedConfig) -> Path:
    """Move a trashed comic back to its place and drop its trace.

    The trace goes first: a file back in the library with its trace still
    there would be skipped by every scan. If the move then fails, the trace
    is written again.

    Returns the restored path; the caller scans it so it reappears at once.
    """
    library_root = config.library_path.resolve()
    trash_root = config.deletion.trash_path
    with Session(get_engine()) as session:
        trace = session.get(DeletedComic, trace_id)
        if trace is None:
            raise DeletionError("Trace not found", status_code=404)
        if trace.mode != "trash" or not trace.trash_path or trash_root is None:
            raise DeletionError("This comic was deleted, not trashed", status_code=409)
        saved = trace.model_dump()

    source = trash_root / saved["trash_path"]
    if not source.is_file():
        raise DeletionError(f"Not in the trash any more: {saved['trash_path']}", status_code=404)
    target = to_absolute(saved["path"], library_root)
    if target.exists():
        raise DeletionError(f"A file already exists at {saved['path']}", status_code=409)

    with Session(get_engine()) as session:
        trace = session.get(DeletedComic, trace_id)
        if trace is None:
            raise DeletionError("Trace not found", status_code=404)
        session.delete(trace)
        session.commit()

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _move(source, target)
    except OSError as exc:
        with Session(get_engine()) as session:
            session.add(DeletedComic(**saved))
            session.commit()
        raise DeletionError(f"Could not restore {saved['filename']}: {exc}") from exc

    logger.info(f"[+] Restored: {saved['path']}")
    return target
