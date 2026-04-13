"""
remarkable-progress-sync: Extract reading progress from reMarkable, update Calibre-Web.

Pipeline:
  1. Query books sync DB for pushed books (have rm_uuid)
  2. rmapi stat each → check ModifiedClient timestamp, skip unchanged
  3. rmapi get changed books → download .rmdoc (zip)
  4. Parse .content JSON for reading position
  5. Map to Calibre book ID via metadata.db
  6. Update Calibre-Web app.db read status
  7. Update books sync DB with progress

Usage:
    remarkable-progress-sync
    remarkable-progress-sync -v
    remarkable-progress-sync --dry-run

Dependencies: rmapi (ddvk fork)
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from booksyncdb import BookSyncDB

DEFAULT_BOOKS_DB = Path("/opt/media/books/.remarkable-books.db")
CALIBRE_METADATA_DB = Path("/opt/media/books/metadata.db")
CALIBRE_WEB_DB = Path("/opt/calibre-web/config/app.db")
RMAPI = Path.home() / ".local" / "bin" / "rmapi"

# Calibre-Web read_status values
STATUS_UNREAD = 0
STATUS_READ = 1
STATUS_READING = 2

# Admin user in Calibre-Web
CALIBRE_USER_ID = 1


def _rmapi() -> str:
    return str(RMAPI) if RMAPI.exists() else "rmapi"


def stat_rm_document(rm_path: str) -> dict:
    """Get metadata via rmapi stat."""
    result = subprocess.run(
        [_rmapi(), "stat", rm_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi stat failed for {rm_path}: {result.stderr}")
    return json.loads(result.stdout)


def download_rmdoc(rm_path: str, output_dir: Path) -> Path:
    """Download a document via rmapi get. Returns path to .rmdoc."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [_rmapi(), "get", rm_path],
        capture_output=True, text=True,
        cwd=str(output_dir),
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi get failed for {rm_path}: {result.stderr}")
    rmdocs = list(output_dir.glob("*.rmdoc"))
    if not rmdocs:
        zips = list(output_dir.glob("*.zip"))
        if zips:
            return zips[-1]
        raise FileNotFoundError(f"No .rmdoc downloaded for {rm_path}")
    return rmdocs[-1]


def extract_content_json(rmdoc_path: Path) -> dict:
    """Extract and parse the .content JSON from an rmdoc zip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        subprocess.run(
            ["unzip", "-qo", str(rmdoc_path), "*.content", "-d", str(tmpdir)],
            capture_output=True,
        )
        content_files = list(tmpdir.glob("*.content"))
        if not content_files:
            raise FileNotFoundError(f"No .content file in {rmdoc_path}")
        return json.loads(content_files[0].read_text())


def parse_reading_progress(content: dict, file_type: str) -> dict:
    """Parse reading progress from .content JSON.

    Returns dict with keys: progress (0.0-1.0), page (int), total_pages (int).
    Returns empty dict if progress cannot be determined.
    """
    result = {}

    if file_type == "pdf":
        return _parse_pdf_progress(content)
    elif file_type == "epub":
        return _parse_epub_progress(content)

    return result


def _parse_pdf_progress(content: dict) -> dict:
    """Parse PDF reading progress from .content JSON.

    PDFs use lastOpenedPage (0-indexed integer) and pageCount.
    """
    page = content.get("lastOpenedPage")
    total = content.get("pageCount")

    if page is None:
        return {}

    # pageCount may be 0 for never-opened docs, try cPages
    if not total and "cPages" in content:
        pages = content["cPages"].get("pages", [])
        if pages:
            total = len(pages)

    # Also try top-level pages array
    if not total and content.get("pages"):
        total = len(content["pages"])

    if not total or total <= 0:
        return {}

    # page is 0-indexed, progress = (page + 1) / total
    progress = min((page + 1) / total, 1.0)

    return {
        "progress": progress,
        "page": page,
        "total_pages": total,
    }


def _parse_epub_progress(content: dict) -> dict:
    """Parse EPUB reading progress from .content JSON.

    EPUBs can use multiple formats:
    1. cPages.lastOpened.value (page UUID) + cPages.pages array → index/total
    2. lastOpenedPage (integer) + pageCount
    """
    # Try cPages format first (firmware v6+, after book has been read)
    if "cPages" in content:
        cpages = content["cPages"]
        pages = cpages.get("pages", [])
        last_opened = cpages.get("lastOpened", {})

        if pages and last_opened:
            last_value = last_opened.get("value")
            if last_value:
                # Find index of lastOpened page in pages array
                page_ids = [p.get("id", p) if isinstance(p, dict) else p for p in pages]
                try:
                    idx = page_ids.index(last_value)
                    total = len(page_ids)
                    progress = min((idx + 1) / total, 1.0)
                    return {
                        "progress": progress,
                        "page": idx,
                        "total_pages": total,
                    }
                except ValueError:
                    pass  # lastOpened not in pages list — fall through

    # Fallback: lastOpenedPage + pageCount (simpler format)
    page = content.get("lastOpenedPage")
    total = content.get("pageCount")

    if page is not None and total and total > 0:
        progress = min((page + 1) / total, 1.0)
        return {
            "progress": progress,
            "page": page,
            "total_pages": total,
        }

    return {}


def find_calibre_book_id(local_path: str, calibre_db_path: Path) -> int | None:
    """Map a BookSyncDB local_path to a Calibre book ID.

    local_path is like "Author/Title (ID)/filename.epub".
    Calibre books.path is like "Author/Title (ID)".
    Match by checking if local_path starts with books.path + "/".
    """
    # Extract directory from local_path
    book_dir = str(Path(local_path).parent)

    conn = sqlite3.connect(str(calibre_db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT id, path, title FROM books WHERE path = ?",
            (book_dir,),
        )
        row = cur.fetchone()
        if row:
            return row["id"]

        # Fallback: partial match (books.path might not have the (ID) suffix in all cases)
        cur = conn.execute(
            "SELECT id, path, title FROM books ORDER BY path"
        )
        for row in cur.fetchall():
            if book_dir.startswith(row["path"]):
                return row["id"]

        return None
    finally:
        conn.close()


def update_calibre_web_progress(
    book_id: int,
    progress: float,
    calibre_web_db_path: Path,
    user_id: int = CALIBRE_USER_ID,
) -> None:
    """Update reading status in Calibre-Web app.db.

    Sets read_status=2 (reading) if progress < 95%, =1 (read) if >= 95%.
    Uses WAL mode, writes quickly, closes immediately.
    """
    read_status = STATUS_READ if progress >= 0.95 else STATUS_READING
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(str(calibre_web_db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        # Check if entry exists
        cur = conn.execute(
            "SELECT id, read_status FROM book_read_link WHERE book_id = ? AND user_id = ?",
            (book_id, user_id),
        )
        existing = cur.fetchone()

        if existing:
            conn.execute(
                "UPDATE book_read_link SET read_status = ?, last_modified = ? "
                "WHERE book_id = ? AND user_id = ?",
                (read_status, now, book_id, user_id),
            )
        else:
            conn.execute(
                "INSERT INTO book_read_link "
                "(book_id, user_id, read_status, last_modified, times_started_reading) "
                "VALUES (?, ?, ?, ?, 1)",
                (book_id, user_id, read_status, now),
            )
        conn.commit()
    finally:
        conn.close()


def list_rm_books(root: str = "/books") -> list[dict]:
    """List all files under a reMarkable folder.

    Returns list of dicts: {name, path, folder}.
    """
    result = subprocess.run(
        [_rmapi(), "find", root],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi find failed: {result.stderr}")

    books = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("[f]"):
            continue
        path = line[4:].strip()
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        folder = path.rsplit("/", 1)[0] if "/" in path else "/"
        if not folder.startswith("/"):
            folder = "/" + folder
        books.append({"name": name, "path": "/" + path if not path.startswith("/") else path, "folder": folder})

    return books


def build_rm_path_index(rm_books: list[dict]) -> dict[str, dict]:
    """Build UUID-to-current-path index by running rmapi stat on each book.

    Also builds a name-based index as fallback for books without UUID in DB.
    Returns {uuid: rm_book_with_metadata, ...}.
    """
    uuid_index = {}
    for rm_book in rm_books:
        try:
            metadata = stat_rm_document(rm_book["path"])
            rm_uuid = metadata.get("ID")
            if rm_uuid:
                rm_book["uuid"] = rm_uuid
                rm_book["metadata"] = metadata
                uuid_index[rm_uuid] = rm_book
        except RuntimeError:
            pass  # stat failed — skip this book
    return uuid_index


def sync_progress(
    db: BookSyncDB,
    calibre_db_path: Path,
    calibre_web_db_path: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    """Sync reading progress for all pushed books. Returns (synced, errors)."""
    books = db.get_all_pushed()
    if not books:
        print("No pushed books in DB.")
        return 0, 0

    # Build fresh UUID-to-path index from reMarkable
    # This handles books that have been moved to different folders
    print("Scanning reMarkable /books for current paths...")
    try:
        rm_books = list_rm_books("/books")
    except RuntimeError as e:
        print(f"ERROR: cannot list reMarkable books: {e}")
        return 0, 0

    # Build name-based index (cheaper than stat-ing every book)
    rm_name_index = {b["name"].lower(): b for b in rm_books}

    if verbose:
        print(f"Found {len(rm_books)} books on reMarkable")
        print(f"Checking {len(books)} pushed book(s) in DB...")

    synced = 0
    errors = 0

    for book in books:
        rm_name = book["rm_name"]
        rm_uuid = book["rm_uuid"]
        local_path = book["local_path"]
        file_type = book["rm_type"]

        # Resolve current path on reMarkable — use name index first
        rm_entry = rm_name_index.get(rm_name.lower()) if rm_name else None

        if not rm_entry:
            if verbose:
                print(f"  SKIP (not found on rM): {rm_name}")
            continue

        rm_path = rm_entry["path"]
        rm_folder = rm_entry["folder"]

        try:
            # Get metadata (includes ModifiedClient and UUID)
            metadata = stat_rm_document(rm_path)
            modified = metadata.get("ModifiedClient", "")
            current_uuid = metadata.get("ID")

            # Update UUID and folder in DB if changed (book was moved)
            if current_uuid and current_uuid != rm_uuid:
                db.upsert_book(local_path=local_path, rm_uuid=current_uuid)
                rm_uuid = current_uuid
            if rm_folder != book.get("rm_folder"):
                db.upsert_book(local_path=local_path, rm_folder=rm_folder)
                if verbose:
                    print(f"  MOVED: {rm_name}: {book.get('rm_folder')} -> {rm_folder}")

            if modified and modified == book.get("rm_modified") and not dry_run:
                if verbose:
                    print(f"  SKIP (unchanged): {rm_name}")
                continue

            if verbose:
                print(f"  Checking: {rm_name} ...", end=" ", flush=True)

            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)

                # Download
                rmdoc_path = download_rmdoc(rm_path, tmpdir)

                # Parse .content
                content = extract_content_json(rmdoc_path)
                progress_data = parse_reading_progress(content, file_type)

                if not progress_data:
                    if verbose:
                        print("no progress data")
                    # Still update rm_modified to avoid re-downloading
                    if local_path:
                        db.upsert_book(local_path=local_path, rm_modified=modified)
                    else:
                        db.upsert_book(rm_uuid=rm_uuid, rm_modified=modified)
                    continue

                progress = progress_data["progress"]
                page = progress_data["page"]
                total_pages = progress_data["total_pages"]

                if verbose:
                    pct = progress * 100
                    print(f"page {page + 1}/{total_pages} ({pct:.0f}%)", end=" ", flush=True)

                if dry_run:
                    if verbose:
                        print("(dry-run)")
                    continue

                # Find Calibre book ID
                if local_path:
                    calibre_id = find_calibre_book_id(local_path, calibre_db_path)
                    if calibre_id is None:
                        print(f"\n  WARNING: no Calibre match for {local_path}")
                    else:
                        update_calibre_web_progress(calibre_id, progress, calibre_web_db_path)
                        if verbose:
                            status_label = "read" if progress >= 0.95 else "reading"
                            print(f"-> calibre #{calibre_id} ({status_label})")
                else:
                    if verbose:
                        print("(no local path, skipping Calibre update)")

                # Update books sync DB
                now = datetime.now(timezone.utc).isoformat()
                update_kwargs = dict(
                    rm_modified=modified,
                    reading_progress=progress,
                    reading_page=page,
                    reading_total_pages=total_pages,
                    reading_updated=now,
                )
                if local_path:
                    db.upsert_book(local_path=local_path, **update_kwargs)
                else:
                    db.upsert_book(rm_uuid=rm_uuid, **update_kwargs)
                db.log("progress", local_path=local_path, rm_path=rm_path,
                       detail=f"page {page + 1}/{total_pages} ({progress * 100:.0f}%)")
                synced += 1

        except Exception as e:
            print(f"\n  ERROR: {rm_name}: {e}")
            errors += 1

    return synced, errors


def main():
    parser = argparse.ArgumentParser(
        description="Sync reading progress from reMarkable to Calibre-Web"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be synced without updating"
    )
    parser.add_argument(
        "--db-path", type=Path, default=DEFAULT_BOOKS_DB,
        help=f"Books sync DB path (default: {DEFAULT_BOOKS_DB})"
    )
    parser.add_argument(
        "--calibre-db", type=Path, default=CALIBRE_METADATA_DB,
        help=f"Calibre metadata.db path (default: {CALIBRE_METADATA_DB})"
    )
    parser.add_argument(
        "--calibre-web-db", type=Path, default=CALIBRE_WEB_DB,
        help=f"Calibre-Web app.db path (default: {CALIBRE_WEB_DB})"
    )
    args = parser.parse_args()

    # Validate DB paths
    if not args.calibre_db.exists():
        print(f"ERROR: Calibre metadata.db not found: {args.calibre_db}")
        sys.exit(1)
    if not args.calibre_web_db.exists():
        print(f"ERROR: Calibre-Web app.db not found: {args.calibre_web_db}")
        sys.exit(1)

    db = BookSyncDB(args.db_path)
    try:
        synced, errors = sync_progress(
            db,
            args.calibre_db,
            args.calibre_web_db,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

        stats = db.stats()
        print(f"\nDone. {synced} synced, {errors} errors.")
        print(f"DB: {stats['total']} books ({stats['pushed']} pushed, "
              f"{stats['with_progress']} with progress)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
