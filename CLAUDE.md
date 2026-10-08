# Issued (fork) — Claude Code instructions

Issued is a self-hosted comic library server: it scans a folder of CBZ/CBR/CB7/PDF files into SQLite and serves it over OPDS and a web reader (FastAPI, SQLModel, Alembic).

This file lives only on the fork's `develop`. It must never reach the author's repository.

## Language

- Talk to the user in the language they use.
- Code, comments, commit messages, PR descriptions and documentation: English.

## Fork workflow

- `origin` = `davidp57/issued`, our fork and working repository. `upstream` = `metalogico/issued`, the author's, default branch `develop`.
- Our `develop` is our integration branch and may diverge from the author's without limit. Internal work branches start from `origin/develop` and open PRs **in the fork**.
- Only chosen changes are shared with the author. A branch meant for the author **starts from `upstream/develop`** (cherry-pick the fix if it already exists on our side), opens a PR to `metalogico/issued`, and the same branch is then merged into our `develop` with a **merge commit**, not a squash, so both sides hold the same commit.
- Before opening a PR to the author, check that `git log upstream/develop..HEAD` lists only the commits of that change.
- Nothing of ours goes to the author: no `CLAUDE.md`, no `docs/agents/`, no tickets.
- **No cross-references** between our issues/PRs and the author's, in either direction: GitHub turns a mention into a "mentioned this" line on the other side.
- Bring the author's work in by merging `upstream/develop` into our `develop`.

## Commands

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on Linux/macOS
.venv/Scripts/python -m pytest -q
```

The suite runs in about ten seconds and must pass on Windows as well as Linux.
Read and write text files with an explicit `encoding="utf-8"`: the Windows default is cp1252.

## CI

- `.github/workflows/ci.yml`: `pytest` on Ubuntu and Windows, plus a Docker build without push, on every PR and on pushes to `develop`.
- `build.yml` and `docker-publish.yml` are the author's release workflows. They push to `ghcr.io/metalogico/...` and are **disabled on the fork** from the Actions settings; leave the files untouched.
- Fork PRs are merged once CI is green.

## Database

- Paths stored in the database are relative to the library root and always use forward slashes (`server/path_utils.py`).
- Schema and data changes go through an Alembic revision under `migrations/versions/`.
- Exception: repairing a table that `SQLModel.metadata.create_all()` built with an outdated definition goes in an `ensure_*` function of `server/migrations.py`, called by `serve` at startup. Such a repair needs no slot in the Alembic chain, so it cannot collide with a revision pending elsewhere, and it must be idempotent.

## Documentation

Update `README.md` in the same change when a user-visible behaviour or setting changes.

## Agent skills

### Issue tracker

Lots, PRDs and tickets are GitHub issues on `davidp57/issued`. See `docs/agents/issue-tracker.md`.

### Triage labels

Matt's triage roles map to GitHub labels. See `docs/agents/triage-labels.md`.

### Domain docs

See `docs/agents/domain.md`.
