"""
Regression test for the per-script exit-code contract.

Contract: every src/remarkable_*.py entry point exits non-zero when any
per-item operation raises inside its main loop. A clean run exits zero.

The afternoon-eating bug this guards against:
    push.main() caught per-file exceptions, printed "ERROR: ...", then
    returned None — so the process exited 0 even when 0/N notes pushed.
    Downstream callers (nvim hook, cron, CI) read exit code and got a
    silent green light on total failure.

We exercise the push path here because it's where the bug surfaced. The
other scripts (pull, push_book, progress_sync, import_to_calibre) already
counted errors locally; the fix in those was a one-line propagation.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import remarkable_push


def _make_vault_with_notes(tmpdir: Path, note_names: list[str]) -> tuple[Path, list[Path]]:
    """Create a fake vault with the given .md filenames. Returns (vault_root, note_paths)."""
    vault = tmpdir / "notes"
    vault.mkdir()
    notes = []
    for name in note_names:
        p = vault / name
        p.write_text(f"# {name}\n\nbody.\n")
        notes.append(p)
    return vault, notes


def _run_push(monkeypatch, note_paths: list[Path], vault: Path) -> int | None:
    """Run remarkable_push.main() with the given argv. Returns the exit code
    (None if main returned cleanly without sys.exit, int otherwise)."""
    argv = ["remarkable-push", "--vault-root", str(vault)] + [str(p) for p in note_paths]
    monkeypatch.setattr(sys, "argv", argv)
    try:
        remarkable_push.main()
        return None
    except SystemExit as e:
        return e.code


def test_push_exits_nonzero_when_all_fail(monkeypatch):
    """All-fail case: every push_note raises → exit non-zero, not 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        vault, notes = _make_vault_with_notes(tmpdir, ["a.md", "b.md"])

        def fake_push(*args, **kwargs):
            raise RuntimeError("simulated pandoc failure")

        monkeypatch.setattr(remarkable_push, "push_note", fake_push)
        code = _run_push(monkeypatch, notes, vault)

        assert code is not None and code != 0, (
            f"push.main() must exit non-zero when all push_note calls fail; got {code!r}"
        )


def test_push_exits_nonzero_on_partial_failure(monkeypatch):
    """Partial-fail case: 1 success + 1 failure → exit non-zero.

    This is the exact scenario that bit G: some files succeeded, so the
    process *looked* like it was working, but a real failure was hidden
    behind exit 0.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Failure comes FIRST so the success after it proves the loop
        # didn't break/return early. (If failure came last, calls==2 would
        # be trivially satisfied and prove nothing about post-failure flow.)
        vault, notes = _make_vault_with_notes(tmpdir, ["bad.md", "good.md"])

        calls = {"n": 0}

        def fake_push(md_path, *args, **kwargs):
            calls["n"] += 1
            if md_path.name == "bad.md":
                raise RuntimeError("simulated rmapi put failure")
            return True

        monkeypatch.setattr(remarkable_push, "push_note", fake_push)
        code = _run_push(monkeypatch, notes, vault)

        assert calls["n"] == 2, "loop must continue past the first failure"
        assert code is not None and code != 0, (
            f"partial-failure run must exit non-zero; got {code!r}"
        )


def test_push_clean_run_exits_zero(monkeypatch):
    """Clean-run case: every push_note succeeds → no SystemExit raised."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        vault, notes = _make_vault_with_notes(tmpdir, ["a.md", "b.md"])

        def fake_push(*args, **kwargs):
            return True

        monkeypatch.setattr(remarkable_push, "push_note", fake_push)
        code = _run_push(monkeypatch, notes, vault)

        # main() returns None on success (no sys.exit). Exit code 0 also acceptable.
        assert code in (None, 0), f"clean run must not exit non-zero; got {code!r}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
