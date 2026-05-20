#!/usr/bin/env python3
"""Interactive OCR scoring tool. Runs on G's LAPTOP (macOS), stdlib only.

Usage:
    cd ~/dev/tools/remarkable-bridge && uv run discovery/score_ocr.py
"""

import json
import os
import sys
from pathlib import Path

DISCOVERY_DIR = Path(__file__).parent
GROUND_TRUTH_DIR = DISCOVERY_DIR / "ground-truth"
RESULTS_DIR = DISCOVERY_DIR / "results"
SCORES_FILE = DISCOVERY_DIR / "scores.json"

DIMENSIONS = [
    ("accuracy", "Character/word correctness"),
    ("structure", "Headings, lists, hierarchy preserved"),
    ("handwriting_tolerance", "Handles messy/cursive input"),
    ("markdown_quality", "Output usable without heavy cleanup"),
    ("edge_cases", "Math, code, diagrams, symbols"),
]

ENGINES = [
    "olmocr2",
    "glm-ocr",
    "remarkable-builtin",
    # R0 baseline (re-pulled for R1 comparison)
    "minicpm-v",
    # R1 (2026-05-20)
    "qwen3-vl",
    "gemma4",
    "deepseek-ocr",
    "granite-vision",
]


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def divider(label="", width=78):
    if label:
        print(f"\n{'─' * 3} {label} {'─' * (width - len(label) - 5)}")
    else:
        print("─" * width)


def get_score(dim, desc):
    while True:
        try:
            raw = input(f"  {dim} ({desc}) [1-5, s=skip, q=quit]: ").strip().lower()
            if raw == "q":
                return "quit"
            if raw == "s":
                return "skip"
            score = int(raw)
            if 1 <= score <= 5:
                return score
            print("    Must be 1-5.")
        except (ValueError, EOFError):
            print("    Must be 1-5, 's' to skip, or 'q' to save and quit.")


def load_scores():
    if SCORES_FILE.exists():
        return json.loads(SCORES_FILE.read_text())
    return {}


def save_scores(scores):
    SCORES_FILE.write_text(json.dumps(scores, indent=2))


def load_timing(engine):
    timing_file = RESULTS_DIR / engine / "timing.json"
    if timing_file.exists():
        return json.loads(timing_file.read_text())
    return {}


def print_summary(scores):
    divider("SUMMARY")
    engines = {}
    for key, entry in scores.items():
        eng = entry["engine"]
        if eng not in engines:
            engines[eng] = {"scores": [], "timing": load_timing(eng)}
        engines[eng]["scores"].append(entry["scores"])

    header = f"{'Engine':<20}"
    for dim, _ in DIMENSIONS:
        header += f"{dim[:12]:<14}"
    header += f"{'AVG':<8}{'s/page':<8}"
    print(f"\n{header}")
    print("─" * len(header))

    for eng, data in sorted(engines.items()):
        row = f"{eng:<20}"
        dim_avgs = []
        for dim, _ in DIMENSIONS:
            vals = [s[dim] for s in data["scores"] if dim in s]
            if vals:
                avg = sum(vals) / len(vals)
                dim_avgs.append(avg)
                row += f"{avg:<14.1f}"
            else:
                row += f"{'n/a':<14}"
        if dim_avgs:
            overall = sum(dim_avgs) / len(dim_avgs)
            row += f"{overall:<8.1f}"
        else:
            row += f"{'n/a':<8}"

        timing = data["timing"]
        if timing:
            all_pages = []
            for tc_data in timing.values():
                all_pages.extend(
                    t["seconds"] for t in tc_data.get("pages", []) if t.get("seconds", -1) > 0
                )
            if all_pages:
                row += f"{sum(all_pages)/len(all_pages):<8.1f}"
            else:
                row += f"{'n/a':<8}"
        else:
            row += f"{'n/a':<8}"

        print(row)

    # PASS/FAIL verdict
    print()
    divider("VERDICT")
    key_cases = ["clean-study", "messy-quick"]
    for eng, data in engines.items():
        accs = []
        for s_entry in data["scores"]:
            # find the test_case for this score set
            pass
        # simpler: check from the raw scores dict
    pass_engines = []
    for eng in engines:
        eng_accs = []
        for key, entry in scores.items():
            if entry["engine"] == eng and entry["test_case"] in key_cases:
                if "accuracy" in entry["scores"]:
                    eng_accs.append(entry["scores"]["accuracy"])
        if eng_accs and sum(eng_accs) / len(eng_accs) >= 3:
            pass_engines.append(eng)

    if pass_engines:
        print(f"PASS: Self-hosted OCR viable. Engines meeting threshold: {pass_engines}")
    else:
        print("FAIL: No self-hosted engine scored ≥3 avg accuracy on clean-study + messy-quick.")
        print("      Consider evaluating ADE (Azure Document Intelligence) as primary.")
    print()


def main():
    available = []
    for eng in ENGINES:
        eng_dir = RESULTS_DIR / eng
        if eng_dir.exists() and any(eng_dir.glob("*.md")):
            available.append(eng)

    if not available:
        print("FAIL: No OCR results found in discovery/results/")
        print("Run OCR first: uv run discovery/run_ocr.py --engine <engine>")
        sys.exit(1)

    gt_files = sorted(GROUND_TRUTH_DIR.glob("*.md"))
    if not gt_files:
        print("FAIL: No ground truth files in discovery/ground-truth/")
        sys.exit(1)

    test_cases = [f.stem for f in gt_files]
    scores = load_scores()

    print(f"Engines with results: {available}")
    print(f"Test cases: {test_cases}")
    print(f"Existing scores: {len(scores)}")
    print()

    for engine in available:
        for tc in test_cases:
            key = f"{engine}/{tc}"
            if key in scores:
                print(f"  SKIP: {key} (already scored)")
                continue

            gt_file = GROUND_TRUTH_DIR / f"{tc}.md"
            result_file = RESULTS_DIR / engine / f"{tc}.md"
            if not result_file.exists():
                print(f"  SKIP: {key} (no result file)")
                continue

            gt_text = gt_file.read_text()
            result_text = result_file.read_text()

            clear_screen()
            divider(f"{engine} / {tc}")
            divider("GROUND TRUTH")
            print(gt_text)
            divider("OCR OUTPUT")
            print(result_text)
            divider("SCORING")

            entry_scores = {}
            quit_requested = False
            skip_requested = False

            for dim, desc in DIMENSIONS:
                result = get_score(dim, desc)
                if result == "quit":
                    quit_requested = True
                    break
                if result == "skip":
                    skip_requested = True
                    break
                entry_scores[dim] = result

            if quit_requested:
                save_scores(scores)
                print(f"\nScores saved ({len(scores)} entries)")
                print_summary(scores)
                return

            if skip_requested:
                print(f"  SKIPPED: {key}")
                continue

            scores[key] = {
                "engine": engine,
                "test_case": tc,
                "scores": entry_scores,
            }
            save_scores(scores)
            print(f"  -> Saved {key}")

    save_scores(scores)
    print(f"\nAll scoring complete. {len(scores)} entries saved to {SCORES_FILE}")
    print_summary(scores)


if __name__ == "__main__":
    main()
