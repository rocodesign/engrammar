#!/bin/bash
# Run Engrammar test suite

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SOURCE_DIR="$(get_repo_root)"
detect_os

# Use deployed venv if available, otherwise look for local venv
if [ -d "$HOME/.engrammar/venv" ]; then
    PYTHON="$(get_venv_bin "$HOME/.engrammar/venv")/python"
    PYTEST="$(get_venv_bin "$HOME/.engrammar/venv")/pytest"
elif [ -d "$SOURCE_DIR/venv" ]; then
    PYTHON="$(get_venv_bin "$SOURCE_DIR/venv")/python"
    PYTEST="$(get_venv_bin "$SOURCE_DIR/venv")/pytest"
else
    echo "Error: No virtualenv found. Run scripts/setup.sh first."
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
"$PYTEST" "$SOURCE_DIR/tests/" "$@"

echo
echo "=== Tests Complete ==="
