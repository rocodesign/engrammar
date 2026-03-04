#!/bin/bash
# Integration tests: MCP tools via Claude CLI (full stdio pipeline)
# Usage: bash tests/integration/test_mcp_tools.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo ""
echo "═══════════════════════════════════════════"
echo "  Engrammar MCP Tools — Integration Tests"
echo "═══════════════════════════════════════════"
echo ""

# Preflight checks
if ! command -v claude &>/dev/null; then
    error "claude CLI not found in PATH"
    exit 1
fi

if [ ! -f "$DB" ]; then
    error "Database not found at $DB"
    exit 1
fi

# Backup DB before any tests
backup_db
echo "DB backed up (pid $$)"
echo ""

# ─── Test cases ──────────────────────────────────────────────────────────────

test_status() {
    local output
    output=$(run_claude "Call the engrammar_status tool. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "Engrammar Status" "status output"
    assert_contains "$output" "active" "status output"
}

test_add() {
    local output
    output=$(run_claude "Call engrammar_add with text='integration-test-engram-xyz123' and category='testing/integration'. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "Added engram" "add output"
    assert_db "SELECT COUNT(*) FROM engrams WHERE text='integration-test-engram-xyz123'" "1"
    assert_db "SELECT category FROM engrams WHERE text='integration-test-engram-xyz123'" "testing/integration"
}

test_search() {
    # Seed engrams for search
    seed_engram "always use absolute imports in Python projects" "development/python"
    seed_engram "prefer const over let in TypeScript" "development/typescript"
    seed_engram "run linter before committing code changes" "development/workflow"

    # Rebuild index so search can find them
    "$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import get_all_active_engrams
from engrammar.core.embeddings import build_index
engrams = get_all_active_engrams()
build_index(engrams)
"

    local output
    output=$(run_claude "Call engrammar_search with query='Python import conventions'. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "absolute imports" "search output"
}

test_update() {
    local eid
    eid=$(seed_engram "old text to be updated" "testing")

    local output
    output=$(run_claude "Call engrammar_update with engram_id=$eid and text='updated text from integration test'. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "Updated engram" "update output"
    assert_db "SELECT text FROM engrams WHERE id=$eid" "updated text from integration test"
}

test_deprecate() {
    local eid
    eid=$(seed_engram "engram to deprecate" "testing")

    local output
    output=$(run_claude "Call engrammar_deprecate with engram_id=$eid and reason='no longer relevant'. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "Deprecated engram" "deprecate output"
    assert_db "SELECT deprecated FROM engrams WHERE id=$eid" "1"
}

test_pin_unpin() {
    local eid
    eid=$(seed_engram "engram to pin and unpin" "testing")

    # Pin
    local output
    output=$(run_claude "Call engrammar_pin with engram_id=$eid. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "Pinned" "pin output"
    assert_db "SELECT pinned FROM engrams WHERE id=$eid" "1"

    # Unpin
    output=$(run_claude "Call engrammar_unpin with engram_id=$eid. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "Unpinned" "unpin output"
    assert_db "SELECT pinned FROM engrams WHERE id=$eid" "0"
}

test_list() {
    seed_engram "frontend list test engram" "dev/frontend"
    seed_engram "backend list test engram" "dev/backend"
    seed_engram "unrelated list test engram" "ops/monitoring"

    local output
    output=$(run_claude "Call engrammar_list with category='dev'. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "frontend list test" "list output"
    assert_contains "$output" "backend list test" "list output"
    assert_not_contains "$output" "unrelated list test" "list output (should be filtered)"
}

test_feedback() {
    local eid
    eid=$(seed_engram "engram for feedback test" "testing")

    local output
    output=$(run_claude "Call engrammar_feedback with engram_id=$eid, applicable=true, and reason='confirmed useful in test'. Return ONLY the raw tool result, nothing else.")

    assert_contains "$output" "feedback" "feedback output"
    assert_db "SELECT times_matched FROM engrams WHERE id=$eid" "1"
}

# ─── Run all tests ───────────────────────────────────────────────────────────

run_test test_status
run_test test_add
run_test test_search
run_test test_update
run_test test_deprecate
run_test test_pin_unpin
run_test test_list
run_test test_feedback

print_summary
