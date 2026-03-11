#!/usr/bin/env bash
# Copy conversation transcripts for benchmarking.
# Strips ENGRAMMAR injection blocks so extraction runs on clean input.
#
# Usage:
#   ./benchmark/copy_transcripts.sh          # 5 largest transcripts
#   ./benchmark/copy_transcripts.sh 3        # 3 largest
#   ./benchmark/copy_transcripts.sh 10 8000  # 10 largest, min 8KB

set -euo pipefail

COUNT="${1:-5}"
MIN_SIZE_KB="${2:-50}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$SCRIPT_DIR/transcripts"
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

# Find the Claude project transcript directory for this project
# Claude stores transcripts keyed by the absolute project path with / replaced by -
PROJECT_KEY=$(echo "$PROJECT_DIR" | sed 's|/|-|g')
TRANSCRIPTS_DIR="$HOME/.claude/projects/$PROJECT_KEY"

if [ ! -d "$TRANSCRIPTS_DIR" ]; then
    echo "No transcripts found at $TRANSCRIPTS_DIR"
    echo "Make sure you've had Claude Code sessions in this project."
    exit 1
fi

mkdir -p "$OUT_DIR"

echo "Source: $TRANSCRIPTS_DIR"
echo "Copying $COUNT largest transcripts (min ${MIN_SIZE_KB}KB)..."
echo

copied=0
# Sort by size descending, skip subagent dirs, filter by min size
find "$TRANSCRIPTS_DIR" -maxdepth 1 -name "*.jsonl" -size +"${MIN_SIZE_KB}k" -print0 \
    | xargs -0 ls -S \
    | head -n "$COUNT" \
    | while read -r src; do
        name=$(basename "$src")
        dest="$OUT_DIR/$name"

        # Strip ENGRAMMAR injection blocks
        sed -E 's/\[ENGRAMMAR_V1\][^[]*\[\/ENGRAMMAR_V1\]//g' "$src" > "$dest"

        src_kb=$(( $(wc -c < "$src") / 1024 ))
        dest_kb=$(( $(wc -c < "$dest") / 1024 ))
        echo "  $name (${src_kb}KB -> ${dest_kb}KB cleaned)"
    done

echo
echo "Done. Transcripts in: $OUT_DIR"
echo "Run benchmark with: python3 benchmark/run_extraction.py"
