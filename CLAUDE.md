# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this?
CLI tool for bidirectional sync between a Markdown notes vault and reMarkable
tablets (rM2 + Paper Pro). Part of G's terminal-centric notes system.

R0 discovery is done. Production code lives in `src/`; `discovery/` is frozen
(reference corpus + the original bash/OCR proof-of-concept that `render.py`
and `ocr.py` superseded).

## Where it runs
Designed for a home server (Linux, Syncthing-managed vault). This macOS
checkout is for *editing* code that executes there — the hardcoded paths
(`/opt/syncthing/data/notes`, `/opt/media/books`, `/opt/calibre-web`) do not
exist locally. Don't try to run end-to-end here; rely on tests and the home
server for live runs.

## Execution model
- Non-sudo: run directly
- Sudo: print for G to run manually
- Results rsync'd to laptop for interactive scoring (discovery only)

## Running things
No `[project.scripts]` console entries — invoke via `uv run`:

    uv run src/remarkable_pull.py [--force|--notebook NAME|--folder PATH|--dry-run|-v]
    uv run src/remarkable_push.py <note.md> [...] [--profile color|grayscale] [--rm-folder /path] [--vault-root PATH] [--force|--no-create|--dry-run]
    uv run src/remarkable_push_book.py [files...] [--scan|--seed] [--books-dir DIR] [--rm-folder /path] [--force|--dry-run|-v]
    uv run src/remarkable_progress_sync.py [-v|--dry-run]
    uv run src/remarkable_import_to_calibre.py [-v|--dry-run]
    uv run src/seed_db.py [--dry-run|--local-only|--rm-only]

Tests:

    uv run pytest tests/                    # all
    uv run pytest tests/test_progress_sync.py::test_parse_reading_progress_epub -v

Python ≥3.12. Use `uv sync` after touching `pyproject.toml`; no install step.

## Architecture (cross-file)

**Pull pipeline** (`remarkable_pull.py` is the hub):

    rmapi find/get → unzip → render.py (rmc → SVG → rsvg-convert → PNG)
                            → ocr.py (Ollama minicpm-v over HTTP)
                            → postprocess.py (frontmatter + tags)
                            → vault .md + attachments/remarkable/*.pdf

**Push pipeline** (notes):

    .md → preprocess.py (strip frontmatter, fix wikilinks)
        → pandoc (--pdf-engine=typst, templates in src/templates/)
        → rmapi put → reMarkable

**Books**: `remarkable_push_book.py` uploads from a Calibre library;
`remarkable_progress_sync.py` reads `.content` JSON back from rM and writes
progress into Calibre-Web's `app.db` (`book_read_link` table).

**State**: two SQLite databases, hash-based change detection (SHA256).

- `/opt/syncthing/data/notes/.remarkable-sync.db` — `documents` (identity
  mapping local_path ↔ rm_uuid, hashes, ModifiedClient) + `sync_log`.
  Schema in `syncdb.py`.
- `/opt/media/books/.remarkable-books.db` — `books` (push state +
  reading_progress 0.0–1.0). Schema in `booksyncdb.py`.

Rendered PNGs/SVGs/PDFs are ephemeral (tempdir), not persisted.

**Scheduling**: `systemd/remarkable-pull.timer` fires every 6h with 5min
jitter; the unit invokes `src/remarkable_pull_scheduled.sh`, which runs
`remarkable_pull.py` then `remarkable_progress_sync.py` and sends ntfy
notifications only on changes/errors. Logs to
`~/.local/share/remarkable-bridge/pull.log` and the systemd journal
(`SyslogIdentifier=remarkable-pull`).

## Key tools (external)
- `rmapi` (ddvk fork) — at `~/.local/bin/rmapi`; cloud CLI
- `rmc` + `rmscene` — Python, in `.venv`; v6 `.rm` parser/renderer
- `rsvg-convert` (librsvg2) — SVG → PNG
- `ollama` (minicpm-v over `http://localhost:11434`) — OCR
- `pandoc` + `typst` — Markdown → PDF
- `calibredb` (via `docker exec lazylibrarian`) — Calibre library writes
- `uv` — Python package manager

## CRITICAL
- `rmapi geta` is BROKEN — use `rmapi get` + `rmc` + `rsvg-convert` instead
- `rmc` CLI: `rmc -t svg -o output.svg input.rm` (one `.rm` file per page)
- Notebook zip structure: `UUID.content` (JSON with page list), `UUID/page-uuid.rm`
- PASS/FAIL gates at each step — stop and report on FAIL
- Do not run sudo commands — print them for G
- All main scripts support `--dry-run`; use it before destructive ops
