"""
remarkable-push: Convert Markdown notes to PDF and upload to reMarkable.

Usage:
    remarkable-push <note.md>                     # Push a single note
    remarkable-push <note1.md> <note2.md>         # Push multiple notes
    remarkable-push --folder <dir>                # Push all .md files in dir
    remarkable-push <note.md> --profile color     # Use color profile
    remarkable-push <note.md> --rm-folder /Study  # Target specific rM folder
    remarkable-push --dry-run <note.md>           # Show what would happen
    remarkable-push --no-create <note.md>         # Only update, never create

Dependencies: pandoc, typst (system), rmapi (system)
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from preprocess import preprocess
from syncdb import SyncDB

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_RM_FOLDER = "/"
RMAPI = Path.home() / ".local" / "bin" / "rmapi"

EXCLUDE_DIRS = {".git", ".obsidian", ".stfolder", ".stversions", "templates", ".trash", "trash"}
EXCLUDE_FILES = {".remarkable-sync-state.json", ".remarkable-pull-state.json", ".remarkable-conflicts.log", ".remarkable-sync.db"}
EXCLUDE_ROOT_FILES = {"CLAUDE.md", "README.md"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preprocess_file(md_path: Path) -> str:
    return preprocess(md_path.read_text())


def render_pdf(
    markdown_text: str,
    output_pdf: Path,
    profile: str = "grayscale",
) -> None:
    template = TEMPLATES_DIR / f"remarkable-{profile}.typ"
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False
    ) as tmp:
        tmp.write(markdown_text)
        tmp_path = Path(tmp.name)

    try:
        cmd = [
            "pandoc", str(tmp_path),
            "-o", str(output_pdf),
            "--pdf-engine=typst",
            f"--template={template}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Pandoc failed: {result.stderr}")
    finally:
        tmp_path.unlink()


def upload_to_remarkable(pdf_path: Path, rm_folder: str) -> None:
    rmapi = str(RMAPI) if RMAPI.exists() else "rmapi"
    # Create directories recursively (rmapi mkdir doesn't support -p)
    if rm_folder != "/":
        parts = rm_folder.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            subprocess.run(
                [rmapi, "mkdir", "/" + "/".join(parts[:i])],
                capture_output=True,
            )
    result = subprocess.run(
        [rmapi, "put", str(pdf_path), rm_folder],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        if "entry already exists" in result.stderr.lower():
            print(f"SKIP (exists as non-PDF on rM)", end=" ", flush=True)
        else:
            raise RuntimeError(f"rmapi put failed: {result.stderr}")


def map_vault_path_to_rm(note_path: Path, vault_root: Path, rm_base: str) -> str:
    """Map a vault file path to a reMarkable folder path.

    ~/notes/journal/2026-03-13.md -> /journal/
    ~/notes/projects/jdrf/design.md -> /projects/jdrf/
    """
    try:
        relative = note_path.parent.relative_to(vault_root)
        if str(relative) == ".":
            return rm_base.rstrip("/") or "/"
        return f"/{relative}" if rm_base == "/" else f"{rm_base}/{relative}"
    except ValueError:
        return rm_base


def push_note(
    md_path: Path,
    profile: str,
    rm_folder: str,
    vault_root: Path,
    dry_run: bool,
    db: SyncDB,
    no_create: bool = False,
) -> bool:
    """Push a single note. Returns True if pushed, False if skipped."""
    md_path = md_path.resolve()
    rel_path = str(md_path.relative_to(vault_root))
    current_hash = file_hash(md_path)

    # Check DB for this document
    doc = db.get_by_local_path(rel_path)

    if doc:
        # Skip remarkable-origin documents — they came FROM the reMarkable
        if doc["origin"] == "remarkable":
            print(f"  SKIP (origin: remarkable): {md_path.name}")
            return False

        # Skip unchanged local documents
        if doc.get("pushed_hash") == current_hash:
            print(f"  SKIP (unchanged): {md_path.name}")
            return False
    elif no_create:
        # Not in DB and --no-create: skip
        print(f"  SKIP (new, --no-create): {md_path.name}")
        return False

    rm_target = map_vault_path_to_rm(md_path, vault_root, rm_folder)
    pdf_name = md_path.stem + ".pdf"
    rm_path = f"{rm_target}/{pdf_name}" if rm_target != "/" else f"/{pdf_name}"

    if dry_run:
        print(f"  DRY RUN: {md_path.name} -> {rm_path}")
        return False

    print(f"  Converting: {md_path.name} ...", end=" ", flush=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / pdf_name

        processed = preprocess_file(md_path)
        render_pdf(processed, pdf_path, profile)
        print("PDF done", end=" ", flush=True)

        upload_to_remarkable(pdf_path, rm_target)
        print("uploaded")

    # Update DB
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_document(
        local_path=rel_path,
        local_hash=current_hash,
        pushed_hash=current_hash,
        rm_folder=rm_target,
        origin="local",
        last_pushed=now,
    )
    db.log("push", local_path=rel_path, rm_path=rm_path,
           detail=f"profile={profile}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Push Markdown notes to reMarkable as PDF"
    )
    parser.add_argument(
        "files", nargs="*", type=Path,
        help="Markdown files to push"
    )
    parser.add_argument(
        "--folder", type=Path,
        help="Push all .md files in this directory"
    )
    parser.add_argument(
        "--profile", default="grayscale",
        choices=["grayscale", "color"],
        help="Rendering profile (default: grayscale)"
    )
    parser.add_argument(
        "--rm-folder", default=DEFAULT_RM_FOLDER,
        help=f"Target folder on reMarkable (default: {DEFAULT_RM_FOLDER})"
    )
    parser.add_argument(
        "--vault-root", type=Path, default=Path.home() / "notes",
        help="Vault root for path mapping (default: ~/notes)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be pushed without doing it"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Push even if file hasn't changed"
    )
    parser.add_argument(
        "--no-create", action="store_true",
        help="Only update existing files on reMarkable, never create new ones"
    )
    args = parser.parse_args()

    vault_root = args.vault_root.resolve()
    db_path = vault_root / ".remarkable-sync.db"
    db = SyncDB(db_path)

    try:
        files = list(args.files) if args.files else []
        if args.folder:
            files.extend(sorted(args.folder.glob("**/*.md")))

        if not files:
            parser.error("No files specified. Use positional args or --folder.")

        def _is_excluded(p: Path) -> bool:
            if p.name.startswith(".") or p.name in EXCLUDE_FILES:
                return True
            if p.resolve().parent == vault_root and p.name in EXCLUDE_ROOT_FILES:
                return True
            return any(part in EXCLUDE_DIRS for part in p.parts)

        files = [f for f in files if f.suffix == ".md" and f.exists() and not _is_excluded(f)]
        if not files:
            print("No .md files found.")
            sys.exit(1)

        if args.force:
            for f in files:
                rel = str(f.resolve().relative_to(vault_root))
                doc = db.get_by_local_path(rel)
                if doc:
                    db.upsert_document(local_path=rel, pushed_hash=None)

        print(f"Pushing {len(files)} note(s) to {args.rm_folder} [{args.profile}]")
        pushed = 0
        errors = 0
        for md_path in files:
            try:
                if push_note(
                    md_path, args.profile, args.rm_folder,
                    vault_root, args.dry_run, db, args.no_create,
                ):
                    pushed += 1
            except Exception as e:
                print(f"\n  ERROR: {md_path.name}: {e}")
                errors += 1

        # Print stats
        stats = db.stats()
        print(f"\nDone. {pushed}/{len(files)} pushed, {errors} errors.")
        print(f"DB: {stats['total']} docs ({stats['local_origin']} local, "
              f"{stats['remarkable_origin']} rM, {stats['pushed']} pushed)")

        if errors:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
