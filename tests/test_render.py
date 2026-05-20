"""
Regression tests for render.extract_notebook_pages per-page resilience.

The rsvg-convert step uses Cairo, which has a hard 16-bit per-dimension cap
(32767 px). A single oversized notebook page (e.g. cys625 in the wild) must
not kill the whole notebook — other pages should still render, and a fully
unrenderable notebook should produce an empty PNG list so the caller can
route it into the render-failed bucket.

Mirrors the existing per-page warn-and-continue pattern already used for
the rmc step in the same loop.
"""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import render


def _make_fake_rmdoc(rmdoc_path: Path, page_ids: list[str], uuid: str = "fake-uuid") -> None:
    """Build a minimal rmdoc zip: UUID.content (notebook fileType) + UUID/<id>.rm files."""
    content = {
        "fileType": "notebook",
        "cPages": {"pages": [{"id": pid} for pid in page_ids]},
    }
    with zipfile.ZipFile(rmdoc_path, "w") as zf:
        zf.writestr(f"{uuid}.content", json.dumps(content))
        for pid in page_ids:
            # Empty .rm — the rmc step is monkeypatched and never reads it.
            zf.writestr(f"{uuid}/{pid}.rm", b"")


def _install_fake_helpers(monkeypatch, rsvg_fail_pages: set[int] | None = None) -> None:
    """Replace the three subprocess/PIL helpers in render with in-memory fakes.

    rsvg_fail_pages: set of page indices (0-based) where _svg_to_png should raise.
    All other pages succeed (svg/png files written; flatten is a no-op).
    """
    fail = rsvg_fail_pages or set()

    def fake_rmc(rm_path: Path, svg_path: Path) -> None:
        svg_path.write_text("<svg/>")

    def fake_rsvg(svg_path: Path, png_path: Path) -> None:
        # SVGs are named page-NNN.svg by extract_notebook_pages.
        idx = int(svg_path.stem.split("-")[1])
        if idx in fail:
            raise RuntimeError(
                "rsvg-convert failed: The resulting image would be larger "
                "than 32767 pixels on either dimension."
            )
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic; content irrelevant

    def fake_flatten(png_path: Path) -> None:
        # Real impl opens with PIL; our fake PNG isn't a valid image, so no-op.
        pass

    monkeypatch.setattr(render, "_render_rm_to_svg", fake_rmc)
    monkeypatch.setattr(render, "_svg_to_png", fake_rsvg)
    monkeypatch.setattr(render, "_flatten_png", fake_flatten)


def test_rsvg_failure_on_one_page_does_not_kill_notebook(monkeypatch, tmp_path):
    """The cys625 scenario: page 1 hits the dimension cap; pages 0 and 2 render fine."""
    rmdoc = tmp_path / "fake.rmdoc"
    _make_fake_rmdoc(rmdoc, ["p-a", "p-b", "p-c"])
    out_dir = tmp_path / "pages"

    _install_fake_helpers(monkeypatch, rsvg_fail_pages={1})

    pngs, _ = render.extract_notebook_pages(rmdoc, out_dir)

    names = sorted(p.name for p in pngs)
    assert names == ["page-000.png", "page-002.png"], (
        f"page 1 should be skipped, others kept; got {names}"
    )


def test_rsvg_failure_on_every_page_returns_empty_pngs(monkeypatch, tmp_path):
    """All pages hit the cap — pngs is empty so pull_notebook routes to render-failed."""
    rmdoc = tmp_path / "fake.rmdoc"
    _make_fake_rmdoc(rmdoc, ["p-1", "p-2"])
    out_dir = tmp_path / "pages"

    _install_fake_helpers(monkeypatch, rsvg_fail_pages={0, 1})

    pngs, _ = render.extract_notebook_pages(rmdoc, out_dir)

    assert pngs == [], (
        f"expected no pngs when every page fails rsvg; got {[p.name for p in pngs]}"
    )


def test_extract_notebook_pages_does_not_raise_on_rsvg_failure(monkeypatch, tmp_path):
    """Pre-fix, _svg_to_png's RuntimeError propagated out of extract_notebook_pages
    and was caught upstream as an 'error' (exit-code-flipping). This guards that
    invariant: rsvg failures stay contained inside the per-page loop."""
    rmdoc = tmp_path / "fake.rmdoc"
    _make_fake_rmdoc(rmdoc, ["only-page"])
    out_dir = tmp_path / "pages"

    _install_fake_helpers(monkeypatch, rsvg_fail_pages={0})

    # The function must return normally (with empty pngs), not raise.
    render.extract_notebook_pages(rmdoc, out_dir)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
