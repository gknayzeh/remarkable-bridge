"""
Sync database for remarkable-bridge.

Single SQLite database tracking the identity mapping between local vault
files and reMarkable documents. Replaces the JSON state files.

Schema:
    documents   — one row per known document (local, rM, or both)
    sync_log    — append-only audit trail of push/pull events
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

    CREATE TABLE IF NOT EXISTS documents (
        -- Identity
        local_path    TEXT UNIQUE,           -- relative to vault root (e.g. journal/2026-03-13.md)
        rm_uuid       TEXT UNIQUE,           -- reMarkable document UUID (null = never seen on rM)
        rm_name       TEXT,                  -- display name on rM (may differ from filename)
        rm_folder     TEXT,                  -- rM folder path (e.g. /learning)
        rm_type       TEXT,                  -- 'notebook', 'epub', 'pdf' (rM document type)

        -- Sync state
        local_hash    TEXT,                  -- SHA256 of local file at last sync
        pushed_hash   TEXT,                  -- SHA256 of content last pushed to rM
        pulled_hash   TEXT,                  -- SHA256 of content last pulled from rM
        rm_modified   TEXT,                  -- ModifiedClient timestamp from rmapi stat

        -- Metadata
        origin        TEXT NOT NULL,         -- 'local' | 'remarkable' (who created the document)
        last_pushed   TEXT,                  -- ISO timestamp
        last_pulled   TEXT,                  -- ISO timestamp
        created_at    TEXT NOT NULL,

        -- At least one identifier must be present
        CHECK (local_path IS NOT NULL OR rm_uuid IS NOT NULL)
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp  TEXT NOT NULL,
        action     TEXT NOT NULL,            -- 'push', 'pull', 'seed', 'delete', 'skip'
        local_path TEXT,
        rm_path    TEXT,
        detail     TEXT                      -- human-readable note
    );

    CREATE INDEX IF NOT EXISTS idx_documents_origin ON documents(origin);
    CREATE INDEX IF NOT EXISTS idx_documents_rm_uuid ON documents(rm_uuid);
    CREATE INDEX IF NOT EXISTS idx_sync_log_action ON sync_log(action);
    """


class SyncDB:
    """Sync state database for remarkable-bridge."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist, run migrations if needed."""
        cur = self.conn.cursor()
        cur.executescript(_schema_sql())

        # Check schema version
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

    # ─── Document CRUD ────────────────────────────────────────────

    def upsert_document(self, **kwargs) -> None:
        """Insert or update a document. Must provide local_path or rm_uuid."""
        now = datetime.now(timezone.utc).isoformat()
        kwargs.setdefault("created_at", now)

        # Determine if this is an update
        existing = None
        if kwargs.get("local_path"):
            existing = self.get_by_local_path(kwargs["local_path"])
        if not existing and kwargs.get("rm_uuid"):
            existing = self.get_by_rm_uuid(kwargs["rm_uuid"])

        if existing:
            # Update — merge new values with existing
            updates = {k: v for k, v in kwargs.items() if v is not None and k != "created_at"}
            if not updates:
                return
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values())
            if existing["local_path"]:
                values.append(existing["local_path"])
                self.conn.execute(
                    f"UPDATE documents SET {set_clause} WHERE local_path = ?", values
                )
            else:
                values.append(existing["rm_uuid"])
                self.conn.execute(
                    f"UPDATE documents SET {set_clause} WHERE rm_uuid = ?", values
                )
        else:
            # Insert
            cols = [k for k in kwargs if kwargs[k] is not None]
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            values = [kwargs[k] for k in cols]
            self.conn.execute(
                f"INSERT INTO documents ({col_names}) VALUES ({placeholders})", values
            )
        self.conn.commit()

    def get_by_local_path(self, local_path: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE local_path = ?", (local_path,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_rm_uuid(self, rm_uuid: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE rm_uuid = ?", (rm_uuid,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_rm_name(self, rm_name: str, rm_folder: str) -> dict | None:
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE rm_name = ? AND rm_folder = ?",
            (rm_name, rm_folder),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_local_documents(self) -> list[dict]:
        """All documents that originated locally."""
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE origin = 'local' ORDER BY local_path"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_pushable(self) -> list[dict]:
        """Documents that originated locally and have been pushed at least once."""
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE origin = 'local' AND rm_uuid IS NOT NULL ORDER BY local_path"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_remarkable_documents(self) -> list[dict]:
        """All documents that originated on reMarkable."""
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE origin = 'remarkable' ORDER BY rm_folder, rm_name"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_all(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM documents ORDER BY local_path")
        return [dict(row) for row in cur.fetchall()]

    def delete_by_local_path(self, local_path: str) -> None:
        self.conn.execute("DELETE FROM documents WHERE local_path = ?", (local_path,))
        self.conn.commit()

    # ─── Sync log ─────────────────────────────────────────────────

    def log(self, action: str, local_path: str = None, rm_path: str = None, detail: str = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO sync_log (timestamp, action, local_path, rm_path, detail) VALUES (?, ?, ?, ?, ?)",
            (now, action, local_path, rm_path, detail),
        )
        self.conn.commit()

    def get_log(self, limit: int = 50) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cur.fetchall()]

    # ─── Stats ────────────────────────────────────────────────────

    def stats(self) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM documents")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM documents WHERE origin = 'local'")
        local = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM documents WHERE origin = 'remarkable'")
        remarkable = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM documents WHERE rm_uuid IS NOT NULL")
        mapped = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM documents WHERE last_pushed IS NOT NULL")
        pushed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM documents WHERE last_pulled IS NOT NULL")
        pulled = cur.fetchone()[0]
        return {
            "total": total,
            "local_origin": local,
            "remarkable_origin": remarkable,
            "mapped_to_rm": mapped,
            "pushed": pushed,
            "pulled": pulled,
        }
