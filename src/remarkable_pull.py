"""
remarkable-pull: Pull notebooks from reMarkable, OCR to Markdown, land in vault.

Usage:
    remarkable-pull                          # Pull all changed notebooks
    remarkable-pull --force                  # Re-pull everything
    remarkable-pull --notebook "clean study" # Pull a specific notebook
    remarkable-pull --folder /Bridge-Test    # Pull from a specific folder
    remarkable-pull --dry-run                # Show what would be pulled
    remarkable-pull -v                       # Verbose output

Pipeline per notebook:
  rmapi get → unzip → rmc (SVG) → rsvg-convert (PNG) → minicpm-v (OCR)
  → post-process → write to vault

Vault output (unified — notes land directly in vault root):
  <vault>/<mirror-of-rm-folders>/<notebook-name>.md
  <vault>/attachments/remarkable/<mirror-of-rm-folders>/<notebook-name>.pdf

Dependencies: rmc (Python, in .venv), rsvg-convert, rmapi, Ollama + minicpm-v
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from render import extract_notebook_pages, extract_original_file, get_file_type
from ocr import ocr_notebook
from postprocess import create_vault_markdown, sanitize_filename, sanitize_folder_path
from syncdb import SyncDB

# Server vault path — Syncthing manages this directory
VAULT_ROOT = Path("/opt/syncthing/data/notes")
ATTACHMENTS_DIR = VAULT_ROOT / "attachments" / "remarkable"
BOOKS_DIR = VAULT_ROOT
DB_PATH = VAULT_ROOT / ".remarkable-sync.db"
CONFLICT_LOG = VAULT_ROOT / ".remarkable-conflicts.log"
RMAPI = Path.home() / ".local" / "bin" / "rmapi"

# Folders managed by other pipelines — skip during notebook pull
EXCLUDE_RM_FOLDERS = {"/books", "books"}


def _rmapi() -> str:
    """Return rmapi path."""
    return str(RMAPI) if RMAPI.exists() else "rmapi"


def stat_notebook(rm_path: str) -> dict:
    """Get metadata for a notebook via rmapi stat.

    Returns dict with keys: ID, Name, Version, ModifiedClient, Type, CurrentPage, Parent.
    """
    result = subprocess.run(
        [_rmapi(), "stat", rm_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi stat failed for {rm_path}: {result.stderr}")
    return json.loads(result.stdout)


def list_all_notebooks(folder: str | None = None) -> list[dict]:
    """Recursively list all files on the reMarkable.

    Uses `rmapi find /` which outputs:
        [f] /path/to/file
        [d] /path/to/folder

    Returns list of dicts with keys: name, path, folder.
    Only returns [f] entries (files, not directories).
    """
    search_root = folder if folder else "/"
    result = subprocess.run(
        [_rmapi(), "find", search_root],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi find failed: {result.stderr}")

    notebooks = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("[f]"):
            continue
        path = line[4:].strip()
        # Skip reMarkable trash
        if path.startswith("/trash/") or path.startswith("trash/") or path == "/trash":
            continue
        # Skip folders managed by other pipelines (e.g. /books → remarkable-push-book)
        if any(path.startswith(f"{ex}/") or path == ex or path.startswith(f"/{ex}/")
               for ex in EXCLUDE_RM_FOLDERS):
            continue
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        parent = path.rsplit("/", 1)[0] if "/" in path else "/"
        notebooks.append({"name": name, "path": path, "folder": parent})

    return notebooks


def download_notebook(rm_path: str, output_dir: Path) -> Path:
    """Download a notebook via rmapi get. Returns path to .rmdoc file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [_rmapi(), "get", rm_path],
        capture_output=True, text=True,
        cwd=str(output_dir),
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmapi get failed for {rm_path}: {result.stderr}")

    # rmapi get produces .rmdoc files
    rmdocs = list(output_dir.glob("*.rmdoc"))
    if not rmdocs:
        # Fallback: check for .zip
        zips = list(output_dir.glob("*.zip"))
        if zips:
            return zips[-1]
        raise FileNotFoundError(f"No .rmdoc downloaded for {rm_path} in {output_dir}")
    return rmdocs[-1]


def pngs_to_pdf(png_paths: list[Path], output_pdf: Path) -> None:
    """Combine PNG pages into a single archival PDF using Pillow."""
    if not png_paths:
        return

    from PIL import Image

    images = []
    for png in sorted(png_paths):
        img = Image.open(png).convert("RGB")
        images.append(img)

    if len(images) == 1:
        images[0].save(output_pdf, "PDF")
    else:
        images[0].save(output_pdf, "PDF", save_all=True, append_images=images[1:])


def resolve_vault_path(intended_path: Path, db: SyncDB, force: bool = False) -> Path | None:
    """Resolve conflicts when the intended vault path already exists.

    Rules:
    1. Path doesn't exist -> use it
    2. Existing file has `source: remarkable` + `status/needs-review` -> overwrite
    3. Existing file has `source: remarkable` + `status/reviewed` -> skip (unless force)
    4. Existing file is a local-origin doc in DB -> CONFLICT
       -> suffix as <name>-handwritten.md, log conflict

    Returns the path to write to, or None if should skip.
    """
    if not intended_path.exists():
        return intended_path

    # Check DB — if this path belongs to a local-origin document, it's a conflict
    rel_path = str(intended_path.relative_to(VAULT_ROOT))
    db_doc = db.get_by_local_path(rel_path)
    if db_doc and db_doc["origin"] == "local":
        suffixed = intended_path.with_stem(intended_path.stem + "-handwritten")
        if suffixed.exists():
            suffixed_content = suffixed.read_text()
            if "status/reviewed" in suffixed_content and not force:
                return None
        log_conflict(intended_path, suffixed)
        return suffixed

    existing_content = intended_path.read_text()

    # Case 2: previous OCR, unreviewed -> overwrite
    if "source: remarkable" in existing_content and "status/needs-review" in existing_content:
        return intended_path

    # Case 3: previous OCR, reviewed -> skip (unless force)
    if "source: remarkable" in existing_content and "status/reviewed" in existing_content:
        if force:
            return intended_path
        return None

    # Fallback: no frontmatter match — treat as overwritable (rM owns it)
    return intended_path


def log_conflict(original: Path, suffixed: Path) -> None:
    """Append to conflict log."""
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"[{timestamp}] CONFLICT: {original} exists (typed note), saved as {suffixed}\n"

    CONFLICT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CONFLICT_LOG.open("a") as f:
        f.write(entry)

    print(f"    CONFLICT: existing typed note at {original.name}, "
          f"saved as {suffixed.name}")


def sync_book(
    notebook: dict,
    db: SyncDB,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Sync a book (epub/pdf) from reMarkable to vault. Returns True if synced."""
    rm_path = notebook["path"]
    name = notebook["name"]
    folder = notebook.get("folder", "/")

    # Check DB — skip if already pulled (unless force)
    doc = db.get_by_rm_name(name, folder)
    if doc and doc.get("last_pulled") and not force:
        if verbose:
            print(f"  SKIP (already synced): {name}")
        return False

    vault_folder = sanitize_folder_path(folder)
    safe_name = sanitize_filename(name)

    if dry_run:
        print(f"  DRY RUN (book): {rm_path} -> {vault_folder}/{safe_name}")
        return False

    print(f"  Syncing book: {name} ...", end=" ", flush=True)

    # Get UUID
    rm_uuid = None
    try:
        metadata = stat_notebook(rm_path)
        rm_uuid = metadata.get("ID")
    except RuntimeError:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download
        rmdoc_path = download_notebook(rm_path, tmpdir / "download")

        # Check file type
        file_type = get_file_type(rmdoc_path)
        if file_type not in ("epub", "pdf"):
            if verbose:
                print(f"SKIP (type: {file_type})")
            # Record type in DB so we don't re-download
            db.upsert_document(
                rm_uuid=rm_uuid,
                rm_name=name,
                rm_folder=folder,
                rm_type=file_type,
                origin="remarkable",
            )
            return False

        # Extract original file
        if vault_folder:
            output_path = BOOKS_DIR / vault_folder / safe_name
        else:
            output_path = BOOKS_DIR / safe_name

        if not extract_original_file(rmdoc_path, output_path):
            print("FAILED (no epub/pdf found in rmdoc)")
            return False

        # Find the actual output file (extract_original_file sets the correct extension)
        actual = next(output_path.parent.glob(f"{safe_name}.*"), None)
        local_rel = str(actual.relative_to(VAULT_ROOT)) if actual else None

        if actual:
            print(f"-> {actual.relative_to(VAULT_ROOT)}")
        else:
            print("done")

    # Update DB
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_document(
        rm_uuid=rm_uuid,
        rm_name=name,
        rm_folder=folder,
        rm_type=file_type,
        local_path=local_rel,
        origin="remarkable",
        last_pulled=now,
    )
    db.log("pull", local_path=local_rel, rm_path=rm_path, detail=f"book ({file_type})")
    return True


def pull_notebook(
    notebook: dict,
    db: SyncDB,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Pull and process a single notebook. Returns True if processed."""
    rm_path = notebook["path"]
    name = notebook["name"]
    folder = notebook.get("folder", "/")

    # Check DB — skip if type is cached as non-notebook
    doc = db.get_by_rm_name(name, folder)
    if doc and doc.get("rm_type") and doc["rm_type"] != "notebook" and not force:
        if verbose:
            print(f"  SKIP (type: {doc['rm_type']}): {name}")
        return False

    # Compute vault paths (unified — directly in vault root)
    vault_folder = sanitize_folder_path(folder)
    safe_name = sanitize_filename(name)
    if vault_folder:
        intended_path = VAULT_ROOT / vault_folder / f"{safe_name}.md"
    else:
        intended_path = VAULT_ROOT / f"{safe_name}.md"

    # Resolve conflicts (handles reviewed protection + typed note conflicts)
    vault_file = resolve_vault_path(intended_path, db, force=force)
    if vault_file is None:
        if verbose:
            print(f"  SKIP (reviewed): {name}")
        return False

    # Check modification time via rmapi stat
    modified_client = ""
    if doc and doc.get("rm_modified") and not force:
        if verbose:
            print(f"    Checking modification time...", end=" ", flush=True)
        try:
            metadata = stat_notebook(rm_path)
            modified_client = metadata.get("ModifiedClient", "")
        except RuntimeError:
            modified_client = ""
        if verbose:
            print(f"{modified_client}")

        if modified_client == doc["rm_modified"]:
            if verbose:
                print(f"  SKIP (unchanged): {name}")
            return False

    if dry_run:
        rel = vault_file.relative_to(VAULT_ROOT)
        print(f"  DRY RUN: {rm_path} -> {rel}")
        return False

    print(f"  Pulling: {name} ...", flush=True)

    # Get UUID and modification time
    rm_uuid = None
    if not modified_client:
        try:
            metadata = stat_notebook(rm_path)
            modified_client = metadata.get("ModifiedClient", "")
            rm_uuid = metadata.get("ID")
        except RuntimeError:
            pass
    elif doc:
        rm_uuid = doc.get("rm_uuid")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download
        if verbose:
            print(f"    Downloading...", end=" ", flush=True)
        rmdoc_path = download_notebook(rm_path, tmpdir / "download")
        if verbose:
            print("done")

        # Check file type — skip non-notebooks and cache the type
        file_type = get_file_type(rmdoc_path)
        if file_type != "notebook":
            if verbose:
                print(f"    SKIP (type: {file_type})")
            db.upsert_document(
                rm_uuid=rm_uuid,
                rm_name=name,
                rm_folder=folder,
                rm_type=file_type,
                origin="remarkable",
            )
            return False

        # Render pages to PNG
        if verbose:
            print(f"    Rendering pages...", end=" ", flush=True)
        png_dir = tmpdir / "pages"
        pngs, _ = extract_notebook_pages(rmdoc_path, png_dir)
        if verbose:
            print(f"{len(pngs)} pages")

        if not pngs:
            print(f"    WARNING: no pages rendered for {name}")
            db.upsert_document(
                rm_uuid=rm_uuid,
                rm_name=name,
                rm_folder=folder,
                rm_type="render-failed",
                origin="remarkable",
            )
            return False

        # OCR
        if verbose:
            print(f"    Running OCR...", end=" ", flush=True)
        ocr_text, ocr_time = ocr_notebook(pngs)
        if verbose:
            print(f"{ocr_time:.1f}s")

        # Generate archival PDF from PNGs
        attachment_folder = ATTACHMENTS_DIR / vault_folder
        attachment_folder.mkdir(parents=True, exist_ok=True)
        pdf_path = attachment_folder / f"{safe_name}.pdf"
        pngs_to_pdf(pngs, pdf_path)
        if verbose:
            print(f"    Archival PDF: {pdf_path}")

        # Post-process and write markdown
        attachment_rel = f"attachments/remarkable/{vault_folder}/{safe_name}.pdf"
        markdown = create_vault_markdown(
            ocr_text=ocr_text,
            notebook_name=name,
            rm_folder=folder,
            page_count=len(pngs),
            attachment_path=attachment_rel,
        )

        vault_file.parent.mkdir(parents=True, exist_ok=True)
        vault_file.write_text(markdown)
        rel = vault_file.relative_to(VAULT_ROOT)
        print(f"    -> {rel} ({len(pngs)} pages, {ocr_time:.1f}s OCR)")

    # Compute hash of written file
    local_hash = hashlib.sha256(vault_file.read_bytes()).hexdigest()
    local_rel = str(vault_file.relative_to(VAULT_ROOT))

    # Update DB
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_document(
        rm_uuid=rm_uuid,
        rm_name=name,
        rm_folder=folder,
        rm_type="notebook",
        local_path=local_rel,
        local_hash=local_hash,
        pulled_hash=local_hash,
        rm_modified=modified_client,
        origin="remarkable",
        last_pulled=now,
    )
    db.log("pull", local_path=local_rel, rm_path=rm_path,
           detail=f"{len(pngs)} pages, {ocr_time:.1f}s OCR")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Pull reMarkable notebooks, OCR to Markdown, land in vault"
    )
    parser.add_argument(
        "--notebook", type=str,
        help="Pull a specific notebook by name (partial match, case-insensitive)"
    )
    parser.add_argument(
        "--folder", type=str,
        help="Only pull from a specific reMarkable folder (e.g., /Bridge-Test)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-pull even if unchanged or already reviewed"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be pulled without doing it"
    )
    parser.add_argument(
        "--sync-books", action="store_true",
        help="Sync books (epub/pdf) from reMarkable to vault (no OCR)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()

    db = SyncDB(DB_PATH)

    try:
        print("Listing reMarkable files...")
        all_files = list_all_notebooks(folder=args.folder)
        print(f"Found {len(all_files)} files")

        # Filter if specific notebook requested
        if args.notebook:
            query = args.notebook.lower()
            all_files = [
                nb for nb in all_files
                if query in nb["name"].lower()
            ]
            if not all_files:
                print(f"No files matching '{args.notebook}'")
                sys.exit(1)
            print(f"Filtered to {len(all_files)} matching '{args.notebook}'")

        pulled = 0
        errors = 0

        if args.sync_books:
            # Sync books mode — find epub/pdf type docs from DB
            book_files = []
            for nb in all_files:
                doc = db.get_by_rm_name(nb["name"], nb.get("folder", "/"))
                if doc and doc.get("rm_type") in ("epub", "pdf"):
                    book_files.append(nb)
            print(f"Found {len(book_files)} books to sync")

            for notebook in book_files:
                try:
                    if sync_book(
                        notebook, db,
                        force=args.force,
                        dry_run=args.dry_run,
                        verbose=args.verbose,
                    ):
                        pulled += 1
                except Exception as e:
                    print(f"  ERROR: {notebook['name']}: {e}")
                    errors += 1
        else:
            # Normal mode — pull handwritten notebooks
            for notebook in all_files:
                try:
                    if pull_notebook(
                        notebook, db,
                        force=args.force,
                        dry_run=args.dry_run,
                        verbose=args.verbose,
                    ):
                        pulled += 1
                except Exception as e:
                    print(f"  ERROR: {notebook['name']}: {e}")
                    errors += 1

        total = len(book_files) if args.sync_books else len(all_files)
        label = "synced" if args.sync_books else "pulled"
        print(f"\nDone. {pulled} {label}, {errors} errors, "
              f"{total - pulled - errors} skipped.")

        # Print DB stats
        stats = db.stats()
        print(f"\nDB: {stats['total']} docs ({stats['local_origin']} local, "
              f"{stats['remarkable_origin']} rM, {stats['mapped_to_rm']} mapped)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
