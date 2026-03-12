#!/usr/bin/env python3
"""Interactive OCR scoring tool. Runs on laptop (macOS), no external deps.

Usage:
    uv run discovery/score_ocr.py

Displays ground truth vs OCR output for each engine × test case and
prompts for scores on five dimensions. Saves to discovery/scores.json.
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
    ("accuracy", "Text correctness — are the words right?"),
    ("structure", "Headings, lists, hierarchy preserved?"),
    ("handwriting_tolerance", "Handles messy/cursive writing?"),
    ("markdown_quality", "Clean, usable Markdown output?"),
    ("edge_cases", "Handles code, math, diagrams, symbols?"),
]

ENGINES = ["olmocr2", "glm-ocr", "ade", "remarkable-builtin"]


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_divider(label: str = "", width: int = 78):
    if label:
        print(f"\n{'─' * 3} {label} {'─' * (width - len(label) - 5)}")
    else:
        print(f"{'─' * width}")


def get_score(dimension: str, description: str) -> int:
    while True:
        try:
            raw = input(f"  {dimension} ({description}) [1-5]: ").strip()
            if raw.lower() == "q":
                return -1  # signal to quit
            score = int(raw)
            if 1 <= score <= 5:
                return score
            print("    Must be 1-5.")
        except (ValueError, EOFError):
            print("    Must be 1-5 (or 'q' to save and quit).")


def load_scores() -> dict:
    if SCORES_FILE.exists():
        return json.loads(SCORES_FILE.read_text())
    return {}


def save_scores(scores: dict):
    SCORES_FILE.write_text(json.dumps(scores, indent=2))


def print_summary(scores: dict):
    print_divider("SUMMARY")
    engines_with_scores = {}

    for key, entry in scores.items():
        engine = entry["engine"]
        if engine not in engines_with_scores:
            engines_with_scores[engine] = []
        engines_with_scores[engine].append(entry["scores"])

    # Header
    print(f"\n{'Engine':<20}", end="")
    for dim, _ in DIMENSIONS:
        print(f"{dim:<22}", end="")
    print(f"{'AVG':<8}")
    print("─" * (20 + 22 * len(DIMENSIONS) + 8))

    for engine, score_list in sorted(engines_with_scores.items()):
        print(f"{engine:<20}", end="")
        dim_avgs = []
        for dim, _ in DIMENSIONS:
            vals = [s[dim] for s in score_list if dim in s]
            if vals:
                avg = sum(vals) / len(vals)
                dim_avgs.append(avg)
                print(f"{avg:<22.1f}", end="")
            else:
                print(f"{'n/a':<22}", end="")
        if dim_avgs:
            overall = sum(dim_avgs) / len(dim_avgs)
            print(f"{overall:<8.1f}")
        else:
            print(f"{'n/a':<8}")
    print()


def main():
    # Find available engines (those with results)
    available_engines = []
    for engine in ENGINES:
        engine_dir = RESULTS_DIR / engine
        if engine_dir.exists() and any(engine_dir.glob("*.md")):
            available_engines.append(engine)

    if not available_engines:
        print("FAIL: No OCR results found in discovery/results/")
        print("Run the OCR engines first: uv run discovery/run_ocr.py --engine <engine>")
        sys.exit(1)

    # Find ground truth files
    gt_files = sorted(GROUND_TRUTH_DIR.glob("*.md"))
    if not gt_files:
        print("FAIL: No ground truth files in discovery/ground-truth/")
        sys.exit(1)

    test_cases = [f.stem for f in gt_files]
    scores = load_scores()

    print(f"Engines with results: {available_engines}")
    print(f"Test cases: {test_cases}")
    print(f"Existing scores: {len(scores)}")
    print("Enter 'q' at any score prompt to save and quit.\n")

    for engine in available_engines:
        for tc in test_cases:
            key = f"{engine}/{tc}"

            # Skip already scored
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
            print_divider(f"{engine} / {tc}")

            print_divider("GROUND TRUTH")
            print(gt_text)

            print_divider("OCR OUTPUT")
            print(result_text)

            print_divider("SCORING")
            entry_scores = {}
            quit_requested = False

            for dim, desc in DIMENSIONS:
                score = get_score(dim, desc)
                if score == -1:
                    quit_requested = True
                    break
                entry_scores[dim] = score

            if quit_requested:
                save_scores(scores)
                print(f"\nScores saved to {SCORES_FILE} ({len(scores)} entries)")
                print_summary(scores)
                return

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
