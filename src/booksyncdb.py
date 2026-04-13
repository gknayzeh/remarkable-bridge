"""
Sync database for remarkable-bridge book tracking.

Separate from the notes sync DB — books have a different lifecycle.
Tracks which books have been pushed to reMarkable and their reading progress.

Default path: /opt/media/books/.remarkable-books.db
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def _schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS books (
        -- Identity
        local_path          TEXT UNIQUE,        -- relative to books dir (e.g. Author/Title/book.epub)
        rm_uuid             TEXT UNIQUE,        -- reMarkable document UUID
        rm_name             TEXT,               -- display name on rM
        rm_folder           TEXT,               -- rM folder path (e.g. /Books)
        rm_type             TEXT,               -- 'epub' or 'pdf'

        -- Sync state
        last_pushed         TEXT,               -- ISO timestamp of last push

        -- Reading progress (from reMarkable)
        reading_progress    REAL,               -- 0.0 to 1.0
        reading_page        INTEGER,            -- current page index
        reading_total_pages INTEGER,            -- total pages
        reading_updated     TEXT,               -- ISO timestamp of last progress sync

        -- Metadata
        rm_modified         TEXT,               -- ModifiedClient from rmapi stat
        created_at          TEXT NOT NULL,

        CHECK (local_path IS NOT NULL OR rm_uuid IS NOT NULL)
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp  TEXT NOT NULL,
        action     TEXT NOT NULL,
        local_path TEXT,
        rm_path    TEXT,
        detail     TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_books_rm_uuid ON books(rm_uuid);
    """


class BookSyncDB:
    """Sync state database for reMarkable book tracking."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(_schema_sql())
        cur.execute("SELECT value FROM meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ─── Book CRUD ────────────────────────────────────────────────

    def upsert_book(self, **kwargs) -> None:
        """Insert or update a book. Must provide local_path or rm_uuid."""
        now = datetime.now(timezone.utc).isoformat()
        kwargs.setdefault("created_at", now)

        existing = None
        if kwargs.get("local_path"):
            existing = self.get_by_local_path(kwargs["local_path"])
        if not existing and kwargs.get("rm_uuid"):
            existing = self.get_by_rm_uuid(kwargs["rm_uuid"])

        if existing:
            updates = {k: v for k, v in kwargs.items() if v is not None and k != "created_at"}
            if not updates:
                return
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values())
            if existing["local_path"]:
                values.append(existing["local_path"])
                self.conn.execute(
                    f"UPDATE books SET {set_clause} WHERE local_path = ?", values
                )
            else:
                values.append(existing["rm_uuid"])
                self.conn.execute(
                    f"UPDATE books SET {set_clause} WHERE rm_uuid = ?", values
                )
        else:
            cols = [k for k in kwargs if kwargs[k] is not None]
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            values = [kwargs[k] for k in cols]
            self.conn.execute(
                f"INSERT INTO books ({col_names}) VALUES ({placeholders})", values
            )
        self.conn.commit()

    def get_by_local_path(self, local_path: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM books WHERE local_path = ?", (local_path,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_rm_uuid(self, rm_uuid: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM books WHERE rm_uuid = ?", (rm_uuid,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_all_pushed(self) -> list[dict]:
        """All books that have been pushed (have rm_uuid)."""
        cur = self.conn.execute(
            "SELECT * FROM books WHERE rm_uuid IS NOT NULL ORDER BY local_path"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_all(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM books ORDER BY local_path")
        return [dict(row) for row in cur.fetchall()]

    # ─── Sync log ─────────────────────────────────────────────────

    def log(self, action: str, local_path: str = None, rm_path: str = None, detail: str = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO sync_log (timestamp, action, local_path, rm_path, detail) VALUES (?, ?, ?, ?, ?)",
            (now, action, local_path, rm_path, detail),
        )
        self.conn.commit()

    # ─── Stats ────────────────────────────────────────────────────

    def stats(self) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM books")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM books WHERE rm_uuid IS NOT NULL")
        pushed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM books WHERE reading_progress IS NOT NULL")
        with_progress = cur.fetchone()[0]
        return {
            "total": total,
            "pushed": pushed,
            "with_progress": with_progress,
        }
