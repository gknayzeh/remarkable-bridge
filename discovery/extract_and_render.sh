#!/usr/bin/env bash
# Extract notebook zips and render .rm pages to SVG then PNG.
# Usage: bash discovery/extract_and_render.sh
# Requires: rmc (Python, in .venv), rsvg-convert (librsvg2-bin)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CORPUS_DIR="${PROJECT_DIR}/discovery/corpus"
RENDERED_DIR="${PROJECT_DIR}/discovery/rendered-pages"
UV="${HOME}/.local/bin/uv"

echo "=== Extract & Render Pipeline ==="

for zip in "${CORPUS_DIR}"/*.zip; do
    name=$(basename "$zip" .zip)
    echo ""
    echo "--- ${name} ---"

    # Extract
    tmpdir=$(mktemp -d)
    unzip -qo "$zip" -d "$tmpdir"

    # Find .content file to get page order
    content_file=$(find "$tmpdir" -name "*.content" -type f | head -1)
    if [ -z "$content_file" ]; then
        echo "  FAIL: no .content file in ${name}.zip"
        rm -rf "$tmpdir"
        continue
    fi

    # Get UUID prefix (directory containing .rm files)
    uuid_dir=$(dirname "$content_file")
    uuid_base=$(basename "$content_file" .content)

    # Get page IDs in order from .content JSON
    page_ids=$(python3 -c "
import json, sys
with open('${content_file}') as f:
    data = json.load(f)
pages = data.get('cPages', {}).get('pages', [])
for p in pages:
    print(p['id'])
")

    mkdir -p "${RENDERED_DIR}/${name}"
    page_num=0

    for page_id in $page_ids; do
        page_num=$((page_num + 1))
        rm_file="${uuid_dir}/${uuid_base}/${page_id}.rm"

        if [ ! -f "$rm_file" ]; then
            echo "  WARN: missing ${page_id}.rm, skipping"
            continue
        fi

        svg_file="${RENDERED_DIR}/${name}/page-$(printf '%02d' $page_num).svg"
        png_file="${RENDERED_DIR}/${name}/page-$(printf '%02d' $page_num).png"

        # Render .rm -> SVG via rmc
        ${UV} --project "${PROJECT_DIR}" run rmc -t svg -o "$svg_file" "$rm_file" 2>/dev/null

        # Convert SVG -> PNG at 300 DPI via rsvg-convert
        rsvg-convert -z 3 -d 300 -p 300 "$svg_file" -o "$png_file"
        ${UV} --project "${PROJECT_DIR}" run python3 "${PROJECT_DIR}/discovery/flatten_png.py" "$png_file"


        size=$(stat -c%s "$png_file" 2>/dev/null || stat -f%z "$png_file")
        echo "  page ${page_num}: $(basename "$rm_file") -> $(basename "$png_file") (${size} bytes)"
    done

    rm -rf "$tmpdir"
done

echo ""
echo "=== Summary ==="
for dir in "${RENDERED_DIR}"/*/; do
    name=$(basename "$dir")
    count=$(find "$dir" -name "*.png" 2>/dev/null | wc -l)
    echo "  ${name}: ${count} PNG(s)"
done
