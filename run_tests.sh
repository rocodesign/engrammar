#!/bin/bash
# Run Engrammar test suite

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    echo "pytest not found. Installing..."
    pip install pytest
fi

echo "=== Running Engrammar Tests ==="
echo

# Run tests with pytest
pytest tests/ "$@"

echo
echo "=== Tests Complete ==="
