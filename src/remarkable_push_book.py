"""
remarkable-push-book: Push EPUB/PDF files from Calibre library to reMarkable.

Usage:
    remarkable-push-book /opt/media/books/Author/Title/book.epub
    remarkable-push-book --scan --books-dir /opt/media/books
    remarkable-push-book --scan --books-dir /opt/media/books --dry-run
    remarkable-push-book --seed                    # Link existing rM books to Calibre
    remarkable-push-book --seed --dry-run          # Show what would be linked
    remarkable-push-book book.pdf --rm-folder /books/python

Dependencies: rmapi (ddvk fork)
"""
import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from booksyncdb import BookSyncDB

DEFAULT_RM_FOLDER = "/books"
DEFAULT_BOOKS_DB = Path("/opt/media/books/.remarkable-books.db")
DEFAULT_CALIBRE_DB = Path("/opt/media/books/metadata.db")
RMAPI = Path.home() / ".local" / "bin" / "rmapi"

BOOK_EXTENSIONS = {".epub", ".pdf"}
EXCLUDE_DIRS = {".caltrash", ".caltmp", ".git", "__pycache__", ".import-staging"}


def _rmapi() -> str:
    return str(RMAPI) if RMAPI.exists() else "rmapi"


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
        # Normalize: ensure folder starts with /
        if not folder.startswith("/"):
            folder = "/" + folder
        books.append({"name": name, "path": "/" + path if not path.startswith("/") else path, "folder": folder})

    return books


def stat_rm_document(rm_path: str) -> dict:
    """Get metadata for a document via rmapi stat. Returns dict with ID, Name, etc."""
    result = subprocess.run(
        [_rmapi(), "stat", rm_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi stat failed for {rm_path}: {result.stderr}")
    return json.loads(result.stdout)


def ensure_rm_folder(rm_folder: str) -> None:
    """Create reMarkable folder hierarchy (rmapi mkdir doesn't support -p)."""
    if rm_folder == "/":
        return
    parts = rm_folder.strip("/").split("/")
    for i in range(1, len(parts) + 1):
        subprocess.run(
            [_rmapi(), "mkdir", "/" + "/".join(parts[:i])],
            capture_output=True,
        )


def upload_book(book_path: Path, rm_folder: str) -> None:
    """Upload a book file to reMarkable via rmapi put."""
    result = subprocess.run(
        [_rmapi(), "put", str(book_path), rm_folder],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        if "entry already exists" in result.stderr.lower():
            print("EXISTS on rM", end=" ", flush=True)
        else:
            raise RuntimeError(f"rmapi put failed: {result.stderr}")


def scan_books(books_dir: Path) -> list[Path]:
    """Find all EPUB/PDF files in the books directory, excluding trash/temp dirs."""
    books = []
    for ext in BOOK_EXTENSIONS:
        for f in books_dir.rglob(f"*{ext}"):
            if not any(part in EXCLUDE_DIRS for part in f.relative_to(books_dir).parts):
                books.append(f)
    return sorted(books)


def find_calibre_book_by_title(title: str, calibre_db_path: Path) -> tuple[int | None, str | None]:
    """Find a Calibre book by title match. Returns (book_id, path) or (None, None)."""
    conn = sqlite3.connect(str(calibre_db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Exact match first
        cur = conn.execute(
            "SELECT id, path FROM books WHERE title = ?", (title,)
        )
        row = cur.fetchone()
        if row:
            return row["id"], row["path"]

        # Case-insensitive match
        cur = conn.execute(
            "SELECT id, path FROM books WHERE LOWER(title) = LOWER(?)", (title,)
        )
        row = cur.fetchone()
        if row:
            return row["id"], row["path"]

        # Substring match — title contains or is contained by the rM name
        cur = conn.execute(
            "SELECT id, title, path FROM books ORDER BY title"
        )
        for row in cur.fetchall():
            calibre_title = row["title"].lower()
            rm_title = title.lower()
            if calibre_title == rm_title or calibre_title.startswith(rm_title) or rm_title.startswith(calibre_title):
                return row["id"], row["path"]

        return None, None
    finally:
        conn.close()


def find_local_path_for_calibre(calibre_path: str, books_dir: Path) -> str | None:
    """Find the actual book file under a Calibre path directory.

    calibre_path is like "Author/Title (ID)".
    Returns relative path like "Author/Title (ID)/book.epub".
    """
    full_dir = books_dir / calibre_path
    if not full_dir.exists():
        return None
    for ext in BOOK_EXTENSIONS:
        files = list(full_dir.glob(f"*{ext}"))
        if files:
            return str(files[0].relative_to(books_dir))
    return None


# ─── Seed mode ────────────────────────────────────────────────


def seed_from_remarkable(
    db: BookSyncDB,
    calibre_db_path: Path,
    books_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, int, int]:
    """Scan reMarkable /books, match to Calibre, populate DB.

    Returns (linked, already_in_db, unmatched).
    """
    print("Scanning reMarkable /books...")
    rm_books = list_rm_books("/books")
    print(f"Found {len(rm_books)} books on reMarkable")

    linked = 0
    already = 0
    unmatched = 0

    for rm_book in rm_books:
        rm_name = rm_book["name"]
        rm_path = rm_book["path"]
        rm_folder = rm_book["folder"]

        # Check if already in DB by name
        # Search all books for matching rm_name
        existing = None
        for book in db.get_all():
            if book.get("rm_name") == rm_name:
                existing = book
                break

        if existing and existing.get("rm_uuid"):
            if verbose:
                print(f"  SKIP (in DB): {rm_name}")
            already += 1
            continue

        # Get UUID
        try:
            metadata = stat_rm_document(rm_path)
            rm_uuid = metadata.get("ID")
        except RuntimeError as e:
            print(f"  ERROR (stat): {rm_name}: {e}")
            unmatched += 1
            continue

        # Match to Calibre
        calibre_id, calibre_path = find_calibre_book_by_title(rm_name, calibre_db_path)
        local_path = None
        if calibre_path:
            local_path = find_local_path_for_calibre(calibre_path, books_dir)

        if dry_run:
            if local_path:
                print(f"  LINK: {rm_name} ({rm_folder}) -> {local_path}")
            else:
                print(f"  LINK (no Calibre match): {rm_name} ({rm_folder})")
            linked += 1
            continue

        if verbose:
            if local_path:
                print(f"  Linking: {rm_name} -> {local_path}")
            else:
                print(f"  Linking (rM only): {rm_name} ({rm_folder})")

        # Determine type from local file or default to epub
        rm_type = None
        if local_path:
            rm_type = Path(local_path).suffix.lstrip(".").lower()
        if not rm_type:
            rm_type = "epub"  # most common default

        now = datetime.now(timezone.utc).isoformat()
        db.upsert_book(
            local_path=local_path,
            rm_uuid=rm_uuid,
            rm_name=rm_name,
            rm_folder=rm_folder,
            rm_type=rm_type,
            last_pushed=now,  # Treat as already synced — don't re-push
        )
        db.log("seed", local_path=local_path, rm_path=rm_path,
               detail=f"calibre_id={calibre_id}" if calibre_id else "no calibre match")
        linked += 1

    return linked, already, unmatched


# ─── Push mode ────────────────────────────────────────────────


def push_book(
    book_path: Path,
    books_dir: Path,
    rm_folder: str,
    dry_run: bool,
    force: bool,
    db: BookSyncDB,
    rm_books_index: dict[str, dict] | None = None,
) -> bool:
    """Push a single book to reMarkable. Returns True if pushed.

    rm_books_index: optional dict of {lowercase_name: rm_book_dict} from list_rm_books(),
    used to detect books already on reMarkable.
    """
    book_path = book_path.resolve()
    rel_path = str(book_path.relative_to(books_dir))
    book_type = book_path.suffix.lstrip(".").lower()

    # Check DB — skip if already pushed unless --force
    doc = db.get_by_local_path(rel_path)
    if doc and doc.get("last_pushed") and not force:
        print(f"  SKIP (already pushed): {book_path.name}")
        return False

    rm_name = book_path.stem

    # Check if already exists on reMarkable (by name)
    if rm_books_index and not force:
        existing = rm_books_index.get(rm_name.lower())
        if existing:
            print(f"  LINK (already on rM): {rm_name} at {existing['path']}")
            # Get UUID and link in DB
            try:
                metadata = stat_rm_document(existing["path"])
                rm_uuid = metadata.get("ID")
            except RuntimeError:
                rm_uuid = None

            now = datetime.now(timezone.utc).isoformat()
            db.upsert_book(
                local_path=rel_path,
                rm_uuid=rm_uuid,
                rm_name=rm_name,
                rm_folder=existing["folder"],
                rm_type=book_type,
                last_pushed=now,
            )
            db.log("link", local_path=rel_path, rm_path=existing["path"],
                   detail="already on rM")
            return False  # Not a new push

    rm_path = f"{rm_folder}/{rm_name}" if rm_folder != "/" else f"/{rm_name}"

    if dry_run:
        print(f"  DRY RUN: {rel_path} -> {rm_path}")
        return False

    print(f"  Uploading: {book_path.name} ...", end=" ", flush=True)

    ensure_rm_folder(rm_folder)
    upload_book(book_path, rm_folder)

    # Get UUID via rmapi stat
    rm_uuid = None
    try:
        metadata = stat_rm_document(rm_path)
        rm_uuid = metadata.get("ID")
        print(f"UUID: {rm_uuid}")
    except RuntimeError as e:
        print(f"uploaded (stat failed: {e})")

    # Update DB
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_book(
        local_path=rel_path,
        rm_uuid=rm_uuid,
        rm_name=rm_name,
        rm_folder=rm_folder,
        rm_type=book_type,
        last_pushed=now,
    )
    db.log("push", local_path=rel_path, rm_path=rm_path,
           detail=f"type={book_type}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Push EPUB/PDF books to reMarkable"
    )
    parser.add_argument(
        "files", nargs="*", type=Path,
        help="Book files (EPUB/PDF) to push"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Scan books directory for all unsynced books"
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="Seed DB from existing reMarkable books (match to Calibre by title)"
    )
    parser.add_argument(
        "--books-dir", type=Path, default=Path("/opt/media/books"),
        help="Books directory (default: /opt/media/books)"
    )
    parser.add_argument(
        "--calibre-db", type=Path, default=DEFAULT_CALIBRE_DB,
        help=f"Calibre metadata.db path (default: {DEFAULT_CALIBRE_DB})"
    )
    parser.add_argument(
        "--rm-folder", default=DEFAULT_RM_FOLDER,
        help=f"Target folder on reMarkable (default: {DEFAULT_RM_FOLDER})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without doing it"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-push even if already synced"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--db-path", type=Path, default=DEFAULT_BOOKS_DB,
        help=f"Books sync DB path (default: {DEFAULT_BOOKS_DB})"
    )
    args = parser.parse_args()

    books_dir = args.books_dir.resolve()
    db = BookSyncDB(args.db_path)

    try:
        # ─── Seed mode ───────────────────────────────────────
        if args.seed:
            linked, already, unmatched = seed_from_remarkable(
                db, args.calibre_db, books_dir,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            stats = db.stats()
            print(f"\nDone. {linked} linked, {already} already in DB, {unmatched} unmatched.")
            print(f"DB: {stats['total']} books ({stats['pushed']} pushed, "
                  f"{stats['with_progress']} with progress)")
            return

        # ─── Push mode ───────────────────────────────────────
        files = list(args.files) if args.files else []

        if args.scan:
            scanned = scan_books(books_dir)
            if not args.force:
                scanned = [
                    f for f in scanned
                    if not db.get_by_local_path(str(f.relative_to(books_dir)))
                    or not db.get_by_local_path(str(f.relative_to(books_dir))).get("last_pushed")
                ]
            files.extend(scanned)

        if not files:
            if args.scan:
                print("No unsynced books found.")
            else:
                parser.error("No files specified. Use positional args, --scan, or --seed.")
            sys.exit(0)

        # Validate files
        valid = []
        for f in files:
            f = f.resolve()
            if not f.exists():
                print(f"  WARNING: file not found: {f}")
                continue
            if f.suffix.lower() not in BOOK_EXTENSIONS:
                print(f"  WARNING: not a supported format ({f.suffix}): {f.name}")
                continue
            valid.append(f)

        if not valid:
            print("No valid book files to push.")
            sys.exit(1)

        # Build index of existing rM books for duplicate detection
        print("Checking existing reMarkable books...")
        try:
            rm_books = list_rm_books("/books")
            rm_books_index = {b["name"].lower(): b for b in rm_books}
            print(f"Found {len(rm_books)} existing books on reMarkable")
        except RuntimeError as e:
            print(f"WARNING: could not list rM books ({e}), skipping duplicate detection")
            rm_books_index = None

        print(f"Pushing {len(valid)} book(s) to {args.rm_folder}")
        pushed = 0
        errors = 0
        for book_path in valid:
            try:
                if push_book(
                    book_path, books_dir, args.rm_folder,
                    args.dry_run, args.force, db,
                    rm_books_index=rm_books_index,
                ):
                    pushed += 1
            except Exception as e:
                print(f"\n  ERROR: {book_path.name}: {e}")
                errors += 1

        stats = db.stats()
        print(f"\nDone. {pushed}/{len(valid)} pushed, {errors} errors.")
        print(f"DB: {stats['total']} books ({stats['pushed']} pushed, "
              f"{stats['with_progress']} with progress)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
