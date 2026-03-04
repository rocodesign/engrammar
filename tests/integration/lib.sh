#!/bin/bash
# Shared helpers for engrammar integration tests
# Usage: source "$(dirname "$0")/lib.sh"

set -e

# ─── Paths ───────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/lib.sh"
detect_os

ENGRAMMAR_HOME="${ENGRAMMAR_HOME:-$HOME/.engrammar}"
DB="$ENGRAMMAR_HOME/engrams.db"
VENV="$(get_venv_bin "$ENGRAMMAR_HOME/venv")/python"

# ─── Test state ──────────────────────────────────────────────────────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_NAMES=()
DB_BACKUP=""

# ─── DB backup / restore ────────────────────────────────────────────────────
backup_db() {
    DB_BACKUP="$ENGRAMMAR_HOME/engrams.db.test-backup-$$"
    cp "$DB" "$DB_BACKUP"
}

restore_db() {
    if [ -n "$DB_BACKUP" ] && [ -f "$DB_BACKUP" ]; then
        cp "$DB_BACKUP" "$DB"
        rm -f "$DB_BACKUP"
    fi
}

# ─── Seed helpers ────────────────────────────────────────────────────────────
seed_engram() {
    local text="$1"
    local category="${2:-general}"
    "$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import add_engram
eid = add_engram(text='$text', category='$category')
print(eid)
"
}

seed_engrams() {
    # Seed multiple engrams, returns space-separated IDs
    local ids=""
    for args in "$@"; do
        local text="${args%%|*}"
        local category="${args#*|}"
        local eid
        eid=$(seed_engram "$text" "$category")
        ids="$ids $eid"
    done
    echo "$ids"
}

# ─── Claude wrapper ─────────────────────────────────────────────────────────
run_claude() {
    local prompt="$1"
    # Unset CLAUDECODE to allow nested claude invocations
    unset CLAUDECODE
    claude -p "$prompt" \
        --no-session-persistence \
        --output-format text \
        --allowedTools 'mcp__engrammar__*' \
        2>/dev/null || true
}

# ─── Assertions ──────────────────────────────────────────────────────────────
assert_contains() {
    local output="$1"
    local expected="$2"
    local label="${3:-output}"
    if echo "$output" | grep -qi "$expected"; then
        return 0
    else
        echo "    ASSERT FAILED: expected $label to contain '$expected'"
        echo "    Got: ${output:0:500}"
        return 1
    fi
}

assert_not_contains() {
    local output="$1"
    local unexpected="$2"
    local label="${3:-output}"
    if echo "$output" | grep -qi "$unexpected"; then
        echo "    ASSERT FAILED: expected $label NOT to contain '$unexpected'"
        echo "    Got: ${output:0:500}"
        return 1
    fi
    return 0
}

assert_db() {
    local query="$1"
    local expected="$2"
    local actual
    actual=$("$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import get_connection
conn = get_connection()
row = conn.execute(\"\"\"$query\"\"\").fetchone()
conn.close()
print(row[0])
")
    if [ "$actual" = "$expected" ]; then
        return 0
    else
        echo "    ASSERT FAILED: DB query returned '$actual', expected '$expected'"
        echo "    Query: $query"
        return 1
    fi
}

# ─── Test runner ─────────────────────────────────────────────────────────────
run_test() {
    local name="$1"
    TESTS_RUN=$((TESTS_RUN + 1))
    printf "  %-40s " "$name"

    # Restore DB to clean state before each test
    restore_db
    backup_db

    if "$name" 2>&1; then
        printf "${GREEN}PASS${RESET}\n"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        printf "${RED}FAIL${RESET}\n"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_NAMES+=("$name")
    fi
}

print_summary() {
    echo ""
    echo "════════════════════════════════════════"
    echo "  Results: $TESTS_PASSED/$TESTS_RUN passed"
    if [ "$TESTS_FAILED" -gt 0 ]; then
        echo "  Failed:"
        for name in "${FAILED_NAMES[@]}"; do
            echo "    - $name"
        done
    fi
    echo "════════════════════════════════════════"

    # Final restore
    restore_db

    if [ "$TESTS_FAILED" -gt 0 ]; then
        return 1
    fi
    return 0
}
