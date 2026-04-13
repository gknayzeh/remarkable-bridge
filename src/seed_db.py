"""
Seed the sync database from git (local files) and rmapi (reMarkable files).

Phase 1: Git-tracked .md files → origin='local'
Phase 2: rmapi find / → origin='remarkable' (only files NOT already mapped)

Usage:
    seed_db.py                      # Seed from both sources
    seed_db.py --dry-run            # Show what would be seeded
    seed_db.py --local-only         # Only seed from git
    seed_db.py --rm-only            # Only seed from reMarkable
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from syncdb import SyncDB

VAULT_ROOT = Path.home() / "notes"
DB_PATH = VAULT_ROOT / ".remarkable-sync.db"
RMAPI = Path.home() / ".local" / "bin" / "rmapi"

# Directories to exclude from local seeding
EXCLUDE_DIRS = {".git", ".obsidian", ".stfolder", ".stversions", "templates", ".trash", "trash"}
EXCLUDE_ROOT_FILES = {"CLAUDE.md", "README.md"}


def _rmapi() -> str:
    return str(RMAPI) if RMAPI.exists() else "rmapi"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_git_tracked_files() -> list[str]:
    """Get all .md files tracked by git in the vault, excluding templates and meta files."""
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        capture_output=True, text=True,
        cwd=str(VAULT_ROOT),
    )
    if result.returncode != 0:
        print(f"git ls-files failed: {result.stderr}", file=sys.stderr)
        return []

    files = []
    for f in result.stdout.strip().split("\n"):
        if not f:
            continue
        parts = Path(f).parts
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        if Path(f).parent == Path(".") and Path(f).name in EXCLUDE_ROOT_FILES:
            continue
        files.append(f)
    return sorted(files)


def get_rm_files() -> list[dict]:
    """Get all files on reMarkable with UUIDs via rmapi stat."""
    # First get the flat list
    result = subprocess.run(
        [_rmapi(), "find", "/"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"rmapi find failed: {result.stderr}", file=sys.stderr)
        return []

    files = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("[f]"):
            continue
        path = line[4:].strip()
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        folder = path.rsplit("/", 1)[0] if "/" in path else "/"
        files.append({"name": name, "path": path, "folder": folder})
    return files


def get_rm_uuid(rm_path: str) -> str | None:
    """Get the UUID for a reMarkable document via rmapi stat."""
    result = subprocess.run(
        [_rmapi(), "stat", rm_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        metadata = json.loads(result.stdout)
        return metadata.get("ID")
    except (json.JSONDecodeError, KeyError):
        return None


def seed_local(db: SyncDB, dry_run: bool = False) -> int:
    """Seed DB with git-tracked local files."""
    files = get_git_tracked_files()
    print(f"Found {len(files)} git-tracked .md files")

    seeded = 0
    for rel_path in files:
        full_path = VAULT_ROOT / rel_path
        if not full_path.exists():
            print(f"  SKIP (missing): {rel_path}")
            continue

        existing = db.get_by_local_path(rel_path)
        if existing:
            print(f"  SKIP (already in DB): {rel_path}")
            continue

        h = file_hash(full_path)

        if dry_run:
            print(f"  SEED (local): {rel_path}")
        else:
            db.upsert_document(
                local_path=rel_path,
                local_hash=h,
                origin="local",
            )
            db.log("seed", local_path=rel_path, detail="seeded from git")
            print(f"  SEED: {rel_path}")
        seeded += 1

    return seeded


def seed_remarkable(db: SyncDB, dry_run: bool = False) -> int:
    """Seed DB with reMarkable files (those not already mapped to local files)."""
    files = get_rm_files()
    print(f"Found {len(files)} files on reMarkable")

    seeded = 0
    for rm_file in files:
        rm_path = rm_file["path"]
        rm_name = rm_file["name"]
        rm_folder = rm_file["folder"]

        # Skip if already in DB by name+folder
        existing = db.get_by_rm_name(rm_name, rm_folder)
        if existing:
            print(f"  SKIP (already in DB): {rm_path}")
            continue

        if dry_run:
            print(f"  SEED (remarkable): {rm_path}")
            seeded += 1
            continue

        # Get UUID
        uuid = get_rm_uuid(rm_path)

        if uuid:
            # Check if UUID already in DB (shouldn't happen but safety check)
            existing_uuid = db.get_by_rm_uuid(uuid)
            if existing_uuid:
                print(f"  SKIP (UUID already in DB): {rm_path}")
                continue

        db.upsert_document(
            rm_uuid=uuid,
            rm_name=rm_name,
            rm_folder=rm_folder,
            origin="remarkable",
        )
        db.log("seed", rm_path=rm_path, detail=f"seeded from rM, uuid={uuid}")
        print(f"  SEED: {rm_path} (uuid={uuid or 'unknown'})")
        seeded += 1

    return seeded


def main():
    parser = argparse.ArgumentParser(description="Seed sync database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be seeded")
    parser.add_argument("--local-only", action="store_true", help="Only seed from git")
    parser.add_argument("--rm-only", action="store_true", help="Only seed from reMarkable")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===\n")

    db = SyncDB(DB_PATH)

    try:
        if not args.rm_only:
            print("─── Phase 1: Seeding from git ───")
            local_count = seed_local(db, dry_run=args.dry_run)
            print(f"  → {local_count} local documents seeded\n")

        if not args.local_only:
            print("─── Phase 2: Seeding from reMarkable ───")
            rm_count = seed_remarkable(db, dry_run=args.dry_run)
            print(f"  → {rm_count} reMarkable documents seeded\n")

        print("─── Stats ───")
        stats = db.stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
