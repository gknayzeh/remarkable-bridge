# remarkable-bridge

## What is this?
CLI tool for bidirectional sync between a Markdown notes vault and reMarkable
tablets (rM2 + Paper Pro). Part of G's terminal-centric notes system.

## Current phase: R0 — Discovery
Evaluating OCR engines and PDF rendering engines. See discovery/.

## Execution model
All work runs on this home server.
- Non-sudo: run directly
- Sudo: print for G to run manually
- Results rsync'd to laptop for interactive scoring

## Key tools
- rmapi (ddvk fork) — reMarkable cloud CLI
- rmc + rmscene — v6 .rm file parser and renderer (SVG/PDF output)
- rsvg-convert (librsvg2) — SVG to PNG
- ollama — local LLM inference (RTX 3080 Max-Q, 16GB VRAM)
- pandoc + typst — Markdown to PDF (for PDF engine comparison)
- uv — Python package manager

## CRITICAL
- rmapi geta is BROKEN — use rmapi get + rmc + rsvg-convert instead
- rmc CLI: `rmc -t svg -o output.svg input.rm` (one .rm file per page)
- Notebook zip structure: UUID.content (JSON with page list), UUID/page-uuid.rm
- PASS/FAIL gates at each step — stop and report on FAIL
- Do not run sudo commands — print them for G
