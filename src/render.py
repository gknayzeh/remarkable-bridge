"""
Render reMarkable notebooks to PNG images for OCR.

Pipeline: .rmdoc (zip) → unzip → parse .content → rmc -t svg → rsvg-convert → PNG

Reuses the proven pipeline from R0 discovery (extract_and_render.sh).
"""
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def extract_notebook_pages(
    rmdoc_path: Path,
    output_dir: Path,
    keep_svgs: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Extract a notebook rmdoc/zip and render each page to PNG.

    Returns (list of PNG paths, list of SVG paths) in page order.
    SVG paths are only populated if keep_svgs=True.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pngs = []
    svgs = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Unzip the .rmdoc (it's a zip archive)
        subprocess.run(
            ["unzip", "-qo", str(rmdoc_path), "-d", str(tmpdir)],
            check=True,
        )

        # Find the .content file to get page order and file type
        content_files = list(tmpdir.glob("*.content"))
        if not content_files:
            raise FileNotFoundError(f"No .content file in {rmdoc_path}")

        content = json.loads(content_files[0].read_text())

        # Check file type — only process notebooks
        file_type = content.get("fileType", "")
        if file_type != "notebook":
            return [], []

        # Get page IDs from cPages format (firmware v6+)
        page_ids = _extract_page_ids(content)

        # UUID prefix — the directory containing .rm files
        uuid_base = content_files[0].stem
        rm_dir = tmpdir / uuid_base

        for i, page_id in enumerate(page_ids):
            rm_file = rm_dir / f"{page_id}.rm"
            if not rm_file.exists():
                print(f"  Warning: page {i} ({page_id}) .rm file missing, skipping")
                continue

            svg_path = tmpdir / f"page-{i:03d}.svg"
            png_path = output_dir / f"page-{i:03d}.png"

            try:
                # rmc render to SVG (matches R0: rmc -t svg -o output input)
                _render_rm_to_svg(rm_file, svg_path)
            except RuntimeError as e:
                print(f"  Warning: page {i} render failed ({e}), skipping")
                continue

            # rsvg/Cairo has a hard 16-bit (32767px) per-dimension cap; skip oversized pages.
            try:
                _svg_to_png(svg_path, png_path)
            except RuntimeError as e:
                print(f"  Warning: page {i} rasterize failed ({e}), skipping")
                continue

            # Flatten RGBA to RGB with white background (matches R0 flatten_png.py)
            _flatten_png(png_path)

            pngs.append(png_path)

            if keep_svgs:
                svg_dest = output_dir / f"page-{i:03d}.svg"
                svg_path.rename(svg_dest)
                svgs.append(svg_dest)

    return pngs, svgs


def extract_original_file(rmdoc_path: Path, output_path: Path) -> bool:
    """Extract the original PDF or epub from an rmdoc.

    The rmdoc contains UUID.epub or UUID.pdf alongside UUID.content.
    Returns True if a file was extracted.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        subprocess.run(
            ["unzip", "-qo", str(rmdoc_path), "-d", str(tmpdir)],
            capture_output=True,
        )
        # Look for .epub or .pdf files
        for ext in ("*.epub", "*.pdf"):
            found = list(tmpdir.glob(ext))
            if found:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # Use the correct extension from the source
                src = found[0]
                dest = output_path.with_suffix(src.suffix)
                import shutil
                shutil.copy2(src, dest)
                return True
    return False


def get_file_type(rmdoc_path: Path) -> str:
    """Check the fileType of an rmdoc without full extraction.

    Returns 'notebook', 'pdf', 'epub', or '' if unknown.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Extract only the .content file
        result = subprocess.run(
            ["unzip", "-qo", str(rmdoc_path), "*.content", "-d", str(tmpdir)],
            capture_output=True,
        )
        if result.returncode != 0:
            return ""
        content_files = list(tmpdir.glob("*.content"))
        if not content_files:
            return ""
        content = json.loads(content_files[0].read_text())
        return content.get("fileType", "")


def _extract_page_ids(content: dict) -> list[str]:
    """Extract ordered page IDs from .content JSON.

    Uses cPages.pages[].id format (firmware v6+, confirmed in R0).
    """
    if "cPages" in content and "pages" in content["cPages"]:
        return [p["id"] for p in content["cPages"]["pages"]]
    # Fallback: older "pages" format
    if "pages" in content:
        return content["pages"]
    raise ValueError(f"Cannot find page IDs in .content: {list(content.keys())}")


def _render_rm_to_svg(rm_path: Path, svg_path: Path) -> None:
    """Render a .rm file to SVG using rmc.

    Matches R0 invocation: rmc -t svg -o output input
    """
    result = subprocess.run(
        ["rmc", "-t", "svg", "-o", str(svg_path), str(rm_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rmc failed on {rm_path}: {result.stderr}")


def _svg_to_png(svg_path: Path, png_path: Path) -> None:
    """Convert SVG to PNG at 3x zoom with 300 DPI.

    Matches R0 invocation: rsvg-convert -z 3 -d 300 -p 300 input -o output
    """
    result = subprocess.run(
        [
            "rsvg-convert",
            "-z", "3",
            "-d", "300",
            "-p", "300",
            str(svg_path),
            "-o", str(png_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rsvg-convert failed: {result.stderr}")


def _flatten_png(png_path: Path) -> None:
    """Flatten RGBA PNG to RGB with white background.

    Matches R0 flatten_png.py — required because rmc renders strokes
    on transparent RGBA background, which breaks OCR.
    """
    img = Image.open(png_path)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        bg.save(png_path)
