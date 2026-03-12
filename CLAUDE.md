# remarkable-bridge

## What is this?
CLI tool for bidirectional sync between a Markdown notes vault and reMarkable
tablets (rM2 + Paper Pro). Part of G's terminal-centric notes system.

## Current phase: R0 — Discovery
Evaluating OCR engines and PDF rendering engines. See `discovery/`.

## Execution model
All heavy work runs on this server (home server).
- Non-sudo commands: run directly
- Sudo commands: print for G to run manually
- Results rsync'd to laptop for interactive scoring

## Project structure
- discovery/corpus/ — PDFs pulled from reMarkable
- discovery/ground-truth/ — pre-written source text
- discovery/rendered-pages/ — PNGs from corpus (300 DPI)
- discovery/results/{engine}/ — OCR output per engine
- discovery/pdf-test/ — PDF rendering comparison
- discovery/scores.json — OCR scoring data
- discovery/DECISIONS.md — final engine selections

## Key tools
- rmapi (ddvk fork) — reMarkable cloud CLI
- ollama — local LLM inference
- pandoc + typst — Markdown to PDF
- pdftoppm (poppler-utils) — PDF to PNG
- uv — Python package manager

## Conventions
- Python 3.12, managed by uv
- PASS/FAIL gates — stop and report on FAIL

## GPU
RTX 3080 Max-Q (16GB VRAM). olmOCR-2 (~9GB Q8) fits. GLM-OCR (~1GB) trivial.
