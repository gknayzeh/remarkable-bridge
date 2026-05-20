"""
remarkable-import-to-calibre: Download rM-only books and add to Calibre library.

One-off import script for books that exist on reMarkable but not in Calibre.

Pipeline per book:
  1. rmapi get → download .rmdoc
  2. Extract original epub/pdf from .rmdoc zip
  3. calibredb add (via docker exec lazylibrarian)
  4. Update BookSyncDB with new local_path

Usage:
    remarkable-import-to-calibre
    remarkable-import-to-calibre --dry-run
    remarkable-import-to-calibre -v
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from booksyncdb import BookSyncDB
from remarkable_push_book import list_rm_books

DEFAULT_BOOKS_DB = Path("/opt/media/books/.remarkable-books.db")
BOOKS_DIR = Path("/opt/media/books")
RMAPI = Path.home() / ".local" / "bin" / "rmapi"

# calibredb inside lazylibrarian container; /books maps to /opt/media/books
CALIBREDB_CMD = ["docker", "exec", "lazylibrarian", "calibredb", "add", "--with-library", "/books"]


def _rmapi() -> str:
    return str(RMAPI) if RMAPI.exists() else "rmapi"


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


def extract_book_file(rmdoc_path: Path, output_dir: Path) -> Path | None:
    """Extract original epub/pdf from .rmdoc zip. Returns path or None."""
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["unzip", "-qo", str(rmdoc_path), "-d", str(output_dir)],
        capture_output=True,
    )
    for ext in ("*.epub", "*.pdf"):
        found = list(output_dir.glob(ext))
        if found:
            return found[0]
    return None


def calibredb_add(book_file: Path, staging_dir: Path) -> tuple[int | None, str | None]:
    """Add a book to Calibre via calibredb. Returns (book_id, calibre_path) or (None, None).

    We copy the file to a staging dir mounted in the container, then run calibredb add.
    """
    import shutil

    # Stage file into /opt/media/books/.import-staging/ (visible as /books/.import-staging/ in container)
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged = staging_dir / book_file.name
    shutil.copy2(book_file, staged)

    container_path = f"/books/.import-staging/{book_file.name}"

    result = subprocess.run(
        CALIBREDB_CMD + [container_path],
        capture_output=True, text=True,
    )

    # Clean up staged file
    staged.unlink(missing_ok=True)

    if result.returncode != 0:
        # "already exist in the calibre database" is not a fatal error
        if "already exist" in result.stdout.lower() or "already exist" in result.stderr.lower():
            return None, None
        raise RuntimeError(f"calibredb add failed: {result.stdout} {result.stderr}")

    # Parse output for book ID: "Added book ids: 123"
    match = re.search(r"Added book ids:\s*(\d+)", result.stdout)
    if match:
        book_id = int(match.group(1))
        # Find the path calibre created
        return book_id, _find_calibre_path(book_id)

    return None, None


def _find_calibre_path(book_id: int) -> str | None:
    """Look up the path Calibre assigned to a book by ID."""
    import sqlite3
    conn = sqlite3.connect(str(BOOKS_DIR / "metadata.db"))
    try:
        cur = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def find_local_file(calibre_path: str) -> str | None:
    """Find the actual book file under a Calibre path. Returns relative path."""
    full_dir = BOOKS_DIR / calibre_path
    if not full_dir.exists():
        return None
    for ext in ("*.epub", "*.pdf"):
        files = list(full_dir.glob(ext))
        if files:
            return str(files[0].relative_to(BOOKS_DIR))
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Import reMarkable-only books into Calibre"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be imported without doing it"
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

    db = BookSyncDB(args.db_path)
    staging_dir = BOOKS_DIR / ".import-staging"

    try:
        # Get rM-only books (no local_path)
        all_books = db.get_all()
        rm_only = [b for b in all_books if b.get("local_path") is None]

        if not rm_only:
            print("No rM-only books to import.")
            return

        # Build name→path index from reMarkable for current paths
        print("Scanning reMarkable for current paths...")
        rm_books = list_rm_books("/books")
        rm_name_index = {b["name"].lower(): b for b in rm_books}
        print(f"Found {len(rm_only)} rM-only books to import")

        imported = 0
        skipped = 0
        errors = 0

        for book in rm_only:
            rm_name = book["rm_name"]
            rm_uuid = book["rm_uuid"]

            # Resolve current path
            rm_entry = rm_name_index.get(rm_name.lower()) if rm_name else None
            if not rm_entry:
                if args.verbose:
                    print(f"  SKIP (not found on rM): {rm_name}")
                skipped += 1
                continue

            rm_path = rm_entry["path"]

            if args.dry_run:
                print(f"  IMPORT: {rm_name} ({rm_entry['folder']})")
                imported += 1
                continue

            print(f"  Importing: {rm_name} ...", end=" ", flush=True)

            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmpdir = Path(tmpdir)

                    # Download
                    rmdoc_path = download_rmdoc(rm_path, tmpdir / "download")

                    # Extract
                    book_file = extract_book_file(rmdoc_path, tmpdir / "extract")
                    if not book_file:
                        print("SKIP (no epub/pdf in rmdoc)")
                        skipped += 1
                        continue

                    file_type = book_file.suffix.lstrip(".").lower()

                    # Add to Calibre
                    book_id, calibre_path = calibredb_add(book_file, staging_dir)

                    if book_id is None:
                        print("SKIP (already in Calibre or add failed)")
                        skipped += 1
                        continue

                    # Find local file path
                    local_path = find_local_file(calibre_path) if calibre_path else None

                    if args.verbose:
                        print(f"calibre #{book_id}", end=" ", flush=True)

                    # Update BookSyncDB
                    db.upsert_book(
                        rm_uuid=rm_uuid,
                        local_path=local_path,
                        rm_type=file_type,
                    )
                    db.log("import", local_path=local_path, rm_path=rm_path,
                           detail=f"calibre_id={book_id}")

                    print(f"OK ({file_type})")
                    imported += 1

            except Exception as e:
                print(f"ERROR: {e}")
                errors += 1

        # Clean up staging dir
        if staging_dir.exists():
            staging_dir.rmdir()

        stats = db.stats()
        print(f"\nDone. {imported} imported, {skipped} skipped, {errors} errors.")
        print(f"DB: {stats['total']} books ({stats['pushed']} pushed)")

        if errors:
            sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
