#!/bin/bash
# Run Engrammar test suite

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use deployed venv if available, otherwise look for local venv
if [ -d "$HOME/.engrammar/venv" ]; then
    PYTHON="$HOME/.engrammar/venv/bin/python"
    PYTEST="$HOME/.engrammar/venv/bin/pytest"
elif [ -d "venv" ]; then
    PYTHON="venv/bin/python"
    PYTEST="venv/bin/pytest"
else
    echo "Error: No virtualenv found. Run setup.sh first."
    exit 1
fi

# Install pytest if not available
if ! "$PYTHON" -c "import pytest" &> /dev/null; then
    echo "Installing pytest..."
    "$PYTHON" -m pip install pytest
fi

echo "=== Running Engrammar Tests ==="
echo

# Run tests with pytest
"$PYTEST" tests/ "$@"

echo
echo "=== Tests Complete ==="
