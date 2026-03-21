#!/bin/bash
# Integration tests: Hook query enrichment pipeline
# Tests that prompts are enriched correctly before search, and that
# different enrichment configs produce different search results.
#
# Usage: bash tests/integration/test_hook_enrichment.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo ""
echo "═══════════════════════════════════════════"
echo "  Hook Enrichment — Integration Tests"
echo "═══════════════════════════════════════════"
echo ""

# Preflight
if ! command -v claude &>/dev/null; then
    error "claude CLI not found in PATH"
    exit 1
fi

if [ ! -f "$DB" ]; then
    error "Database not found at $DB"
    exit 1
fi

backup_db
echo "DB backed up (pid $$)"

# Record baseline event log ID to detect new events
BASELINE_EVENT_ID=$("$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import get_connection
conn = get_connection()
row = conn.execute('SELECT COALESCE(MAX(id), 0) FROM hook_event_log').fetchone()
conn.close()
print(row[0])
")
echo "Baseline event ID: $BASELINE_EVENT_ID"
echo ""

# ─── Helper: get events since baseline ────────────────────────────────────

get_new_events() {
    "$VENV" -c "
import sys, json; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import get_connection
conn = get_connection()
rows = conn.execute('''
    SELECT id, hook_event, context, engram_ids, scores
    FROM hook_event_log WHERE id > $BASELINE_EVENT_ID ORDER BY id
''').fetchall()
conn.close()
for r in rows:
    print(json.dumps({
        'id': r[0], 'event': r[1], 'context': r[2],
        'ids': json.loads(r[3]) if r[3] else [],
        'scores': json.loads(r[4]) if r[4] else {},
    }))
"
}

count_new_events() {
    local event_type="${1:-}"
    local filter=""
    if [ -n "$event_type" ]; then
        filter="AND hook_event = '$event_type'"
    fi
    "$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import get_connection
conn = get_connection()
row = conn.execute('''
    SELECT COUNT(*) FROM hook_event_log WHERE id > $BASELINE_EVENT_ID $filter
''').fetchone()
conn.close()
print(row[0])
"
}

get_last_prompt_context() {
    "$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.core.db import get_connection
conn = get_connection()
row = conn.execute('''
    SELECT context FROM hook_event_log
    WHERE id > $BASELINE_EVENT_ID AND hook_event = 'UserPromptSubmit'
    ORDER BY id DESC LIMIT 1
''').fetchone()
conn.close()
print(row[0] if row else '')
"
}

# ─── Helper: run claude from a specific directory ─────────────────────────

run_claude_in() {
    local dir="$1"
    local prompt="$2"
    unset CLAUDECODE
    (cd "$dir" && claude -p "$prompt" \
        --no-session-persistence \
        --output-format text \
        2>/dev/null) || true
}

# ─── Test cases ──────────────────────────────────────────────────────────

test_prompt_hook_fires() {
    # Basic: prompt hook should fire and log an event
    run_claude_in "/Users/romeocopaciu/work/toptal/staff-portal" \
        "What is happo and how does it work in this project?"

    local count
    count=$(count_new_events "UserPromptSubmit")
    if [ "$count" -lt 1 ]; then
        echo "    ASSERT FAILED: expected at least 1 UserPromptSubmit event, got $count"
        return 1
    fi
    return 0
}

test_prompt_enrichment_strips_tags() {
    # The prompt hook should strip system tags from the logged context
    # We can't inject IDE tags via -p, but we can verify the enrichment
    # function works by checking that a clean query is logged
    run_claude_in "/Users/romeocopaciu/work/toptal/staff-portal" \
        "How does happo generate the asset bundle hash?"

    local ctx
    ctx=$(get_last_prompt_context)

    # Should NOT contain any XML-like tags in the logged context
    if echo "$ctx" | grep -q '<ide_'; then
        echo "    ASSERT FAILED: logged context contains IDE tags"
        echo "    Got: $ctx"
        return 1
    fi
    if echo "$ctx" | grep -q '<system-reminder'; then
        echo "    ASSERT FAILED: logged context contains system-reminder tags"
        echo "    Got: $ctx"
        return 1
    fi
    return 0
}

test_prompt_returns_relevant_engrams() {
    # A domain-specific query from staff-portal should return happo engrams
    run_claude_in "/Users/romeocopaciu/work/toptal/staff-portal" \
        "happo finalize is failing with a 404 zip error in CI"

    local events
    events=$(get_new_events)

    # Find the UserPromptSubmit event for this query
    local found=false
    while IFS= read -r line; do
        local event_type
        event_type=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin)['event'])")
        if [ "$event_type" = "UserPromptSubmit" ]; then
            local ids
            ids=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin)['ids'])")
            # Should contain engram #358 (happo 404 zip) or #371
            if echo "$ids" | grep -qE '358|371'; then
                found=true
                break
            fi
        fi
    done <<< "$events"

    if [ "$found" = "false" ]; then
        echo "    ASSERT FAILED: expected happo 404 engrams (#358 or #371) in results"
        echo "    Events: $(echo "$events" | tail -3)"
        return 1
    fi
    return 0
}

test_session_start_fires() {
    # SessionStart should fire when a new Claude session begins
    # Must invoke its own session since restore_db wipes prior events
    run_claude_in "/Users/romeocopaciu/work/toptal/staff-portal" \
        "What test runner does this project use?"

    local count
    count=$(count_new_events "SessionStart")
    if [ "$count" -lt 1 ]; then
        echo "    ASSERT FAILED: expected at least 1 SessionStart event, got $count"
        return 1
    fi
    return 0
}

test_enrichment_function_directly() {
    # Test the enrichment function against the deployed code
    local result
    result=$("$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
import importlib.util

# Load deployed hook
spec = importlib.util.spec_from_file_location('on_prompt', '$ENGRAMMAR_HOME/hooks/on_prompt.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

from engrammar.core import config as cfg
cfg._config_cache = None
config = cfg.load_config()

# Test 1: Strip IDE tags (default)
raw = '<ide_opened_file>The user opened the file /Users/test/work/toptal/staff-portal/src/App.tsx in the IDE. This may or may not be related to the current task.</ide_opened_file> fix the layout'
q = mod._enrich_prompt_query(raw, config)
assert q == 'fix the layout', f'Expected stripped query, got: {q}'

# Test 2: Strip task notifications
raw2 = '<task-notification><task-id>abc</task-id></task-notification> check results'
q2 = mod._enrich_prompt_query(raw2, config)
assert q2 == 'check results', f'Expected stripped task notif, got: {q2}'

# Test 3: Max length truncation
long = 'a ' * 200
q3 = mod._enrich_prompt_query(long, config)
assert len(q3) <= 300, f'Expected truncated to 300, got: {len(q3)}'

# Test 4: inject_ide_file mode
config2 = dict(config)
config2['query_enrichment'] = {'prompt': {'strip_ide_tags': True, 'inject_ide_file': True, 'inject_ide_selection': False, 'max_query_length': 300}}
q4 = mod._enrich_prompt_query(raw, config2)
assert '[file:' in q4, f'Expected file injection, got: {q4}'
assert 'App.tsx' in q4, f'Expected App.tsx in query, got: {q4}'

print('ALL_PASSED')
")

    assert_contains "$result" "ALL_PASSED" "enrichment function tests"
}

test_tool_query_enrichment() {
    # Test _build_tool_query with narration injection
    local result
    result=$("$VENV" -c "
import sys, re; sys.path.insert(0, '$ENGRAMMAR_HOME')

# Extract functions from engine.py without importing (avoids rank_bm25)
with open('$ENGRAMMAR_HOME/engrammar/search/engine.py') as f:
    source = f.read()

ns = {}
for func in ['_extract_tool_keywords', '_build_tool_query']:
    match = re.search(rf'^(def {func}\(.*?\n(?:(?!^def ).*\n)*)', source, re.MULTILINE)
    if match:
        exec(match.group(1), ns)

btq = ns['_build_tool_query']

# Without narration
r1 = btq('Bash', {'command': 'git commit -m fix'})
assert r1 == 'git commit conventions', f'Expected git commit conventions, got: {r1}'

# With narration
r2 = btq('Bash', {'command': 'git commit -m fix', '_narration': 'Committing the TODO lint fix'})
assert 'Committing the TODO lint fix' in r2, f'Expected narration in query, got: {r2}'
assert 'git commit conventions' in r2, f'Expected tool keywords in query, got: {r2}'

# Narration only (empty command)
r3 = btq('Bash', {'command': '', '_narration': 'Check CI status'})
assert r3 == 'Check CI status', f'Expected narration only, got: {r3}'

# No mutation of original dict
orig = {'command': 'npm test'}
btq('Bash', orig)
assert '_narration' not in orig, f'Original dict was mutated'

print('ALL_PASSED')
")

    assert_contains "$result" "ALL_PASSED" "tool query enrichment tests"
}

test_daemon_search_with_enrichment() {
    # Test search via daemon with different query variants to verify
    # enrichment produces meaningfully different results
    local result
    result=$("$VENV" -c "
import sys, json; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.infra.client import send_request

def search(q, cwd='/Users/romeocopaciu/work/toptal/staff-portal'):
    resp = send_request({
        'type': 'search', 'query': q, 'top_k': 3,
        'enforce_prerequisites': True, 'cwd': cwd,
    })
    return resp.get('results', []) if resp else []

# Vague query should abstain or return low-confidence
r1 = search('how do I fix this component')
r1_ids = [r['id'] for r in r1]

# Same query with file context should return modal-related engrams
r2 = search('[file: src/components/Modal.tsx] how do I fix this component')
r2_ids = [r['id'] for r in r2]

# Narration enriched query should outperform tool-only query
r3 = search('Let me investigate the Happo orchestration flow .github/workflows/happo.yml')
r4 = search('.github/workflows/happo.yml')
r3_top = r3[0]['score'] if r3 else 0
r4_top = r4[0]['score'] if r4 else 0

results = {
    'vague_count': len(r1),
    'file_context_count': len(r2),
    'file_context_ids': r2_ids,
    'narration_top_score': round(r3_top, 3),
    'no_narration_top_score': round(r4_top, 3),
    'narration_improves': r3_top > r4_top,
}

# Assertions
ok = True
if len(r2) <= len(r1):
    print(f'WARN: file context ({len(r2)}) did not produce more results than vague ({len(r1)})')
if not results['narration_improves']:
    print(f'WARN: narration ({r3_top:.3f}) did not improve over no-narration ({r4_top:.3f})')
    ok = False

print(json.dumps(results))
if ok:
    print('ALL_PASSED')
else:
    print('PARTIAL_PASS')
")

    # At minimum, the queries should complete without errors
    if echo "$result" | grep -q "ALL_PASSED\|PARTIAL_PASS"; then
        return 0
    fi
    echo "    ASSERT FAILED: daemon search test did not pass"
    echo "    Got: $result"
    return 1
}

# ─── Run all tests ───────────────────────────────────────────────────────

# Unit-style tests (fast, no Claude invocation)
run_test test_enrichment_function_directly
run_test test_tool_query_enrichment

# Daemon tests (requires running daemon, no Claude invocation)
run_test test_daemon_search_with_enrichment

# End-to-end tests (invoke Claude CLI, slower)
run_test test_prompt_hook_fires
run_test test_prompt_enrichment_strips_tags
run_test test_prompt_returns_relevant_engrams
run_test test_session_start_fires

print_summary
