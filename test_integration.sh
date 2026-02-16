#!/bin/bash
# Integration test: backup DB, run backfill + eval, then probe hook injections
set -e

ENGRAMMAR_HOME="${ENGRAMMAR_HOME:-$HOME/.engrammar}"
DB="$ENGRAMMAR_HOME/lessons.db"
BACKUP="$ENGRAMMAR_HOME/lessons.db.backup-$(date +%Y%m%d-%H%M%S)"
VENV="$ENGRAMMAR_HOME/venv/bin/python"
REPORT_DIR="/tmp/engrammar-integration-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$REPORT_DIR"

echo "=== Engrammar Integration Test ==="
echo "Report dir: $REPORT_DIR"
echo ""

# ── Step 1: Backup DB ──────────────────────────────────────────────
echo "── Step 1: Backing up database ──"
cp "$DB" "$BACKUP"
echo "Backed up to: $BACKUP"
echo ""

# ── Step 2: Current state snapshot ─────────────────────────────────
echo "── Step 2: Current state ──"
"$VENV" -c "
import sys, json; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.db import get_lesson_count, get_pinned_lessons, get_connection, get_all_active_lessons

count = get_lesson_count()
pinned = get_pinned_lessons()
lessons = get_all_active_lessons()

conn = get_connection()
audits = conn.execute('SELECT COUNT(*) FROM session_audit').fetchone()[0]
evals = conn.execute(\"SELECT COUNT(*) FROM processed_relevance_sessions WHERE status='completed'\").fetchone()[0]
pending = conn.execute(\"SELECT COUNT(*) FROM session_audit sa LEFT JOIN processed_relevance_sessions prs ON sa.session_id = prs.session_id WHERE prs.session_id IS NULL OR (prs.status != 'completed' AND prs.retry_count < 3)\").fetchone()[0]
conn.close()

print(f'Active lessons:    {count}')
print(f'Pinned lessons:    {len(pinned)}')
print(f'Audit records:     {audits}')
print(f'Completed evals:   {evals}')
print(f'Pending evals:     {pending}')
print()

# Write lesson summary
with open('$REPORT_DIR/01-lessons.json', 'w') as f:
    json.dump([{'id': l['id'], 'text': l['text'][:100], 'category': l['category'], 'pinned': l['pinned'], 'times_matched': l['times_matched']} for l in lessons], f, indent=2)
print('Wrote lesson summary to $REPORT_DIR/01-lessons.json')

# Write pinned
with open('$REPORT_DIR/02-pinned.json', 'w') as f:
    json.dump([{'id': p['id'], 'text': p['text'][:100], 'prerequisites': p.get('prerequisites')} for p in pinned], f, indent=2)
"
echo ""

# ── Step 3: Run backfill ───────────────────────────────────────────
echo "── Step 3: Running backfill (creates audit records for new sessions) ──"
"$VENV" "$(dirname "$0")/backfill_stats.py" --verbose 2>&1 | tee "$REPORT_DIR/03-backfill.log"
echo ""

# ── Step 4: Run evaluator ─────────────────────────────────────────
echo "── Step 4: Running evaluator (scoring lesson relevance via Haiku) ──"
echo "Checking for pending evaluations..."
PENDING=$("$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.db import get_unprocessed_audit_sessions
sessions = get_unprocessed_audit_sessions(limit=50)
print(len(sessions))
")
echo "Pending evaluations: $PENDING"

if [ "$PENDING" -gt 0 ]; then
    echo "Running evaluator for up to 10 sessions..."
    "$VENV" -c "
import sys; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.db import get_unprocessed_audit_sessions
from engrammar.evaluator import run_evaluation_for_session

sessions = get_unprocessed_audit_sessions(limit=10)
completed = 0
failed = 0

for i, session in enumerate(sessions, 1):
    sid = session['session_id']
    tp = session.get('transcript_path', '(none)')
    print(f'  [{i}/{len(sessions)}] Evaluating {sid[:12]}... (transcript: {tp})', flush=True)
    success = run_evaluation_for_session(sid)
    if success:
        completed += 1
        print(f'    -> completed', flush=True)
    else:
        failed += 1
        print(f'    -> FAILED', flush=True)

print(f'  ---')
print(f'  Completed: {completed}')
print(f'  Failed:    {failed}')
print(f'  Total:     {len(sessions)}')
" 2>&1 | tee "$REPORT_DIR/04-evaluator.log"
else
    echo "No pending evaluations."
fi
echo ""

# ── Step 5: Post-eval state ────────────────────────────────────────
echo "── Step 5: Post-eval state ──"
"$VENV" -c "
import sys, json; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.db import get_pinned_lessons, get_connection

pinned = get_pinned_lessons()
conn = get_connection()
evals = conn.execute(\"SELECT COUNT(*) FROM processed_relevance_sessions WHERE status='completed'\").fetchone()[0]

# Get tag relevance scores
scores = conn.execute('SELECT lesson_id, tag, score, positive_evals, negative_evals FROM lesson_tag_relevance ORDER BY lesson_id, tag').fetchall()
conn.close()

print(f'Pinned after eval:    {len(pinned)}')
print(f'Completed evals:      {evals}')
print(f'Tag relevance entries: {len(scores)}')

if pinned:
    print()
    print('Pinned lessons:')
    for p in pinned:
        print(f'  #{p[\"id\"]}: {p[\"text\"][:80]}')

# Write tag relevance
with open('$REPORT_DIR/05-tag-relevance.json', 'w') as f:
    json.dump([dict(r) for r in scores], f, indent=2)
print(f'Wrote tag relevance to $REPORT_DIR/05-tag-relevance.json')
"
echo ""

# ── Step 6: Probe hook injections with claude ──────────────────────
echo "── Step 6: Probing hook injections ──"
echo ""

# Unset CLAUDECODE to allow nested claude invocations
unset CLAUDECODE

# 6a. SessionStart + UserPromptSubmit probe
echo "  6a. SessionStart + prompt injection probe..."
claude -p "You are being tested. Your ONLY job is to report what [ENGRAMMAR_V1] blocks appear in your context.

Instructions:
1. Look for ANY text between [ENGRAMMAR_V1] and [/ENGRAMMAR_V1] tags in system-reminder blocks
2. For each block found, list:
   - The hook event that injected it (SessionStart or UserPromptSubmit or PreToolUse)
   - Every lesson with its EG#ID and full text
3. If you see NO [ENGRAMMAR_V1] blocks, say 'NO ENGRAMMAR LESSONS INJECTED'

Output format:
## Hook: <event name>
- EG#<id>: <full lesson text>

Do NOT fabricate lessons. Only report what you actually see." \
  --no-session-persistence --output-format text 2>"$REPORT_DIR/06a-stderr.txt" > "$REPORT_DIR/06a-session-prompt.txt" || true
echo "  Wrote to $REPORT_DIR/06a-session-prompt.txt"
cat "$REPORT_DIR/06a-session-prompt.txt"
echo ""

# 6b. Prompt with coding context to trigger relevant lessons
echo "  6b. Coding-context prompt probe..."
claude -p "You are being tested. Your ONLY job is to report what [ENGRAMMAR_V1] blocks appear in your context.

First, report ALL [ENGRAMMAR_V1] blocks you see (from SessionStart and UserPromptSubmit hooks).

My actual prompt context is: I need to create a new React component with Tailwind CSS styling for a Acme app-repo frontend feature. I'll need to create a git branch and PR.

Instructions:
1. List every [ENGRAMMAR_V1] block with the hook event and all EG#IDs
2. If none, say 'NO ENGRAMMAR LESSONS INJECTED'

Output format:
## Hook: <event name>
- EG#<id>: <full lesson text>" \
  --no-session-persistence --output-format text 2>"$REPORT_DIR/06b-stderr.txt" > "$REPORT_DIR/06b-coding-prompt.txt" || true
echo "  Wrote to $REPORT_DIR/06b-coding-prompt.txt"
cat "$REPORT_DIR/06b-coding-prompt.txt"
echo ""

# 6c. Tool use probe — ask Claude to read a file, which triggers PreToolUse
echo "  6c. Tool-use probe (triggers PreToolUse hook)..."
claude -p "You are being tested. Do these two things IN ORDER:

STEP 1: Read the file /Users/user/work/ai-tools/engrammar/README.md using the Read tool.

STEP 2: After reading, report ALL [ENGRAMMAR_V1] blocks you saw in your ENTIRE context — including from SessionStart, UserPromptSubmit, AND PreToolUse hooks.

For each block:
- State which hook event injected it
- List every EG#ID and its full lesson text

If no blocks at all, say 'NO ENGRAMMAR LESSONS INJECTED'

Output format:
## Hook: <event name>
- EG#<id>: <full lesson text>" \
  --no-session-persistence --output-format text 2>"$REPORT_DIR/06c-stderr.txt" > "$REPORT_DIR/06c-tool-use.txt" || true
echo "  Wrote to $REPORT_DIR/06c-tool-use.txt"
cat "$REPORT_DIR/06c-tool-use.txt"
echo ""

# ── Summary ────────────────────────────────────────────────────────
echo ""
echo "=== Integration Test Complete ==="
echo "Reports:  $REPORT_DIR"
echo "DB backup: $BACKUP"
echo ""
echo "To restore DB: cp '$BACKUP' '$DB'"
echo ""
ls -la "$REPORT_DIR"/
