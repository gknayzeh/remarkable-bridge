"""
Tests for remarkable_progress_sync reading progress parsing and Calibre mapping.

Uses real temporary SQLite files, no mocks for DB.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from remarkable_progress_sync import (
    parse_reading_progress,
    find_calibre_book_id,
    update_calibre_web_progress,
    STATUS_READ,
    STATUS_READING,
)
from booksyncdb import BookSyncDB


# ─── EPUB parsing ─────────────────────────────────────────────


def test_epub_cpages_format():
    """EPUB with cPages.lastOpened.value + cPages.pages array."""
    content = {
        "fileType": "epub",
        "lastOpenedPage": 0,
        "pageCount": 0,
        "cPages": {
            "lastOpened": {"value": "page-uuid-3"},
            "pages": [
                {"id": "page-uuid-1"},
                {"id": "page-uuid-2"},
                {"id": "page-uuid-3"},
                {"id": "page-uuid-4"},
                {"id": "page-uuid-5"},
            ],
        },
    }
    result = parse_reading_progress(content, "epub")
    assert result["page"] == 2  # 0-indexed
    assert result["total_pages"] == 5
    assert abs(result["progress"] - 0.6) < 0.01  # (2+1)/5


def test_epub_last_page_cpages():
    """EPUB at the last page via cPages format."""
    content = {
        "fileType": "epub",
        "cPages": {
            "lastOpened": {"value": "page-5"},
            "pages": [
                {"id": "page-1"},
                {"id": "page-2"},
                {"id": "page-3"},
                {"id": "page-4"},
                {"id": "page-5"},
            ],
        },
    }
    result = parse_reading_progress(content, "epub")
    assert result["progress"] == 1.0
    assert result["page"] == 4
    assert result["total_pages"] == 5


def test_epub_simple_format():
    """EPUB with lastOpenedPage + pageCount (simpler/older format)."""
    content = {
        "fileType": "epub",
        "lastOpenedPage": 42,
        "pageCount": 200,
    }
    result = parse_reading_progress(content, "epub")
    assert result["page"] == 42
    assert result["total_pages"] == 200
    assert abs(result["progress"] - 43 / 200) < 0.01


def test_epub_no_progress():
    """EPUB with no reading data (just pushed, never opened)."""
    content = {
        "fileType": "epub",
        "lastOpenedPage": 0,
        "pageCount": 0,
        "pages": None,
    }
    result = parse_reading_progress(content, "epub")
    assert result == {}


# ─── PDF parsing ──────────────────────────────────────────────


def test_pdf_progress():
    """PDF with lastOpenedPage and pageCount."""
    content = {
        "fileType": "pdf",
        "lastOpenedPage": 10,
        "pageCount": 50,
    }
    result = parse_reading_progress(content, "pdf")
    assert result["page"] == 10
    assert result["total_pages"] == 50
    assert abs(result["progress"] - 11 / 50) < 0.01


def test_pdf_cpages_fallback():
    """PDF where pageCount is 0 but cPages has pages."""
    content = {
        "fileType": "pdf",
        "lastOpenedPage": 3,
        "pageCount": 0,
        "cPages": {
            "pages": [
                {"id": "p1"},
                {"id": "p2"},
                {"id": "p3"},
                {"id": "p4"},
                {"id": "p5"},
                {"id": "p6"},
                {"id": "p7"},
                {"id": "p8"},
                {"id": "p9"},
                {"id": "p10"},
            ],
        },
    }
    result = parse_reading_progress(content, "pdf")
    assert result["page"] == 3
    assert result["total_pages"] == 10
    assert abs(result["progress"] - 0.4) < 0.01


def test_pdf_first_page():
    """PDF on first page."""
    content = {
        "fileType": "pdf",
        "lastOpenedPage": 0,
        "pageCount": 100,
    }
    result = parse_reading_progress(content, "pdf")
    assert result["page"] == 0
    assert result["total_pages"] == 100
    assert abs(result["progress"] - 0.01) < 0.01


def test_pdf_no_page_count():
    """PDF with lastOpenedPage but no pageCount at all."""
    content = {
        "fileType": "pdf",
        "lastOpenedPage": 5,
    }
    result = parse_reading_progress(content, "pdf")
    assert result == {}


# ─── Graceful handling of unknown/missing fields ──────────────


def test_unknown_file_type():
    """Unknown file type returns empty dict."""
    content = {"fileType": "notebook", "lastOpenedPage": 5}
    result = parse_reading_progress(content, "notebook")
    assert result == {}


def test_empty_content():
    """Empty .content JSON."""
    result = parse_reading_progress({}, "epub")
    assert result == {}


def test_cpages_missing_last_opened():
    """cPages exists but lastOpened is missing."""
    content = {
        "fileType": "epub",
        "cPages": {
            "pages": [{"id": "p1"}, {"id": "p2"}],
        },
    }
    result = parse_reading_progress(content, "epub")
    assert result == {}


def test_cpages_last_opened_not_in_pages():
    """cPages.lastOpened.value doesn't match any page ID — falls through."""
    content = {
        "fileType": "epub",
        "lastOpenedPage": 0,
        "pageCount": 0,
        "cPages": {
            "lastOpened": {"value": "nonexistent-uuid"},
            "pages": [{"id": "p1"}, {"id": "p2"}],
        },
    }
    result = parse_reading_progress(content, "epub")
    # Falls through to simple format, but pageCount is 0 → empty
    assert result == {}


def test_cpages_empty_pages_list():
    """cPages with empty pages array."""
    content = {
        "fileType": "epub",
        "cPages": {
            "lastOpened": {"value": "some-uuid"},
            "pages": [],
        },
    }
    result = parse_reading_progress(content, "epub")
    assert result == {}


# ─── Calibre book ID mapping ─────────────────────────────────


def _create_calibre_db(db_path: Path, books: list[tuple[int, str, str]]):
    """Create a minimal Calibre metadata.db with books table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            path TEXT
        )
    """)
    for book_id, title, path in books:
        conn.execute(
            "INSERT INTO books (id, title, path) VALUES (?, ?, ?)",
            (book_id, title, path),
        )
    conn.commit()
    conn.close()


def test_calibre_exact_match():
    """Match local_path directory to Calibre books.path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "metadata.db"
        _create_calibre_db(db_path, [
            (1, "Test Book", "Author Name/Test Book (1)"),
            (2, "Other Book", "Author Name/Other Book (2)"),
        ])
        result = find_calibre_book_id(
            "Author Name/Test Book (1)/Test Book - Author Name.epub",
            db_path,
        )
        assert result == 1


def test_calibre_no_match():
    """No matching Calibre book."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "metadata.db"
        _create_calibre_db(db_path, [
            (1, "Test Book", "Author Name/Test Book (1)"),
        ])
        result = find_calibre_book_id(
            "Unknown Author/Unknown Book (99)/file.epub",
            db_path,
        )
        assert result is None


def test_calibre_partial_match():
    """Partial match where local_path dir starts with books.path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "metadata.db"
        _create_calibre_db(db_path, [
            (42, "Deep Work", "Cal Newport/Deep Work (42)"),
        ])
        # Exact match should work since parent dir matches
        result = find_calibre_book_id(
            "Cal Newport/Deep Work (42)/Deep Work - Cal Newport.pdf",
            db_path,
        )
        assert result == 42


# ─── Calibre-Web update ──────────────────────────────────────


def _create_calibre_web_db(db_path: Path):
    """Create a minimal Calibre-Web app.db with book_read_link table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE user (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    conn.execute("INSERT INTO user (id, name) VALUES (1, 'admin')")
    conn.execute("""
        CREATE TABLE book_read_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            user_id INTEGER,
            read_status INTEGER NOT NULL,
            last_modified DATETIME,
            last_time_started_reading DATETIME,
            times_started_reading INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES user (id)
        )
    """)
    conn.commit()
    conn.close()


def test_calibre_web_insert_reading():
    """Insert new reading status (progress < 95%)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "app.db"
        _create_calibre_web_db(db_path)

        update_calibre_web_progress(1, 0.5, db_path)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT book_id, user_id, read_status FROM book_read_link WHERE book_id = 1"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 1  # book_id
        assert row[1] == 1  # user_id
        assert row[2] == STATUS_READING  # 2


def test_calibre_web_insert_read():
    """Insert read status (progress >= 95%)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "app.db"
        _create_calibre_web_db(db_path)

        update_calibre_web_progress(1, 0.96, db_path)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT read_status FROM book_read_link WHERE book_id = 1"
        ).fetchone()
        conn.close()

        assert row[0] == STATUS_READ  # 1


def test_calibre_web_update_existing():
    """Update existing reading status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "app.db"
        _create_calibre_web_db(db_path)

        # First: reading
        update_calibre_web_progress(1, 0.3, db_path)
        # Second: finished
        update_calibre_web_progress(1, 0.98, db_path)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT read_status FROM book_read_link WHERE book_id = 1"
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM book_read_link WHERE book_id = 1"
        ).fetchone()
        conn.close()

        assert row[0] == STATUS_READ
        assert count[0] == 1  # only one row, updated in place


# ─── BookSyncDB integration ──────────────────────────────────


def test_booksyncdb_roundtrip():
    """BookSyncDB stores and retrieves book data correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test-books.db"
        db = BookSyncDB(db_path)
        try:
            db.upsert_book(
                local_path="Author/Book (1)/book.epub",
                rm_uuid="abc-123",
                rm_name="book",
                rm_folder="/Books",
                rm_type="epub",
                last_pushed="2026-04-10T00:00:00+00:00",
            )

            book = db.get_by_local_path("Author/Book (1)/book.epub")
            assert book is not None
            assert book["rm_uuid"] == "abc-123"
            assert book["rm_type"] == "epub"

            # Update progress
            db.upsert_book(
                local_path="Author/Book (1)/book.epub",
                reading_progress=0.42,
                reading_page=20,
                reading_total_pages=48,
                reading_updated="2026-04-10T12:00:00+00:00",
            )

            book = db.get_by_local_path("Author/Book (1)/book.epub")
            assert book["reading_progress"] == 0.42
            assert book["reading_page"] == 20
            assert book["reading_total_pages"] == 48

            pushed = db.get_all_pushed()
            assert len(pushed) == 1
            assert pushed[0]["rm_uuid"] == "abc-123"

            stats = db.stats()
            assert stats["total"] == 1
            assert stats["pushed"] == 1
            assert stats["with_progress"] == 1
        finally:
            db.close()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
