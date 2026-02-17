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

# ── Step 3: Extract lessons from transcripts ─────────────────────
echo "── Step 3: Extracting lessons from conversation transcripts ──"
"$VENV" "$(dirname "$0")/cli.py" extract --limit 10 2>&1 | tee "$REPORT_DIR/03-extract.log"
echo ""

# ── Step 3b: Backfill prerequisites ──────────────────────────────
echo "── Step 3b: Backfilling prerequisites on lessons ──"
"$VENV" "$(dirname "$0")/cli.py" backfill-prereqs 2>&1 | tee "$REPORT_DIR/03b-prereqs.log"
echo ""

# ── Step 4: Post-extraction state ─────────────────────────────────
echo "── Step 4: Post-extraction state ──"
"$VENV" -c "
import sys, json; sys.path.insert(0, '$ENGRAMMAR_HOME')
from engrammar.db import get_lesson_count, get_pinned_lessons, get_all_active_lessons, get_connection

count = get_lesson_count()
pinned = get_pinned_lessons()
lessons = get_all_active_lessons()

conn = get_connection()
processed = conn.execute('SELECT COUNT(*) FROM processed_sessions').fetchone()[0]
conn.close()

print(f'Active lessons:       {count}')
print(f'Pinned lessons:       {len(pinned)}')
print(f'Processed sessions:   {processed}')

if pinned:
    print()
    print('Pinned lessons:')
    for p in pinned:
        print(f'  #{p[\"id\"]}: {p[\"text\"][:80]}')

# Write updated lesson summary
with open('$REPORT_DIR/04-lessons-after.json', 'w') as f:
    json.dump([{'id': l['id'], 'text': l['text'][:100], 'category': l['category'], 'source': l.get('source', 'unknown')} for l in lessons], f, indent=2)
print(f'Wrote post-extraction lessons to $REPORT_DIR/04-lessons-after.json')
"
echo ""

# ── Step 5: Probe hook injections with claude ──────────────────────
echo "── Step 5: Probing hook injections ──"
echo ""

# Unset CLAUDECODE to allow nested claude invocations
unset CLAUDECODE

# 5a. SessionStart + UserPromptSubmit probe
echo "  5a. SessionStart + prompt injection probe..."
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
  --no-session-persistence --output-format text 2>"$REPORT_DIR/05a-stderr.txt" > "$REPORT_DIR/05a-session-prompt.txt" || true
echo "  Wrote to $REPORT_DIR/05a-session-prompt.txt"
cat "$REPORT_DIR/05a-session-prompt.txt"
echo ""

# 5b. Prompt with coding context to trigger relevant lessons
echo "  5b. Coding-context prompt probe..."
claude -p "You are being tested. Your ONLY job is to report what [ENGRAMMAR_V1] blocks appear in your context.

First, report ALL [ENGRAMMAR_V1] blocks you see (from SessionStart and UserPromptSubmit hooks).

My actual prompt context is: I need to create a new React component with Tailwind CSS styling for a frontend feature. I'll need to create a git branch and PR.

Instructions:
1. List every [ENGRAMMAR_V1] block with the hook event and all EG#IDs
2. If none, say 'NO ENGRAMMAR LESSONS INJECTED'

Output format:
## Hook: <event name>
- EG#<id>: <full lesson text>" \
  --no-session-persistence --output-format text 2>"$REPORT_DIR/05b-stderr.txt" > "$REPORT_DIR/05b-coding-prompt.txt" || true
echo "  Wrote to $REPORT_DIR/05b-coding-prompt.txt"
cat "$REPORT_DIR/05b-coding-prompt.txt"
echo ""

# 5c. Tool use probe — ask Claude to read a file, which triggers PreToolUse
echo "  5c. Tool-use probe (triggers PreToolUse hook)..."
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
  --no-session-persistence --output-format text 2>"$REPORT_DIR/05c-stderr.txt" > "$REPORT_DIR/05c-tool-use.txt" || true
echo "  Wrote to $REPORT_DIR/05c-tool-use.txt"
cat "$REPORT_DIR/05c-tool-use.txt"
echo ""

# ── Summary ────────────────────────────────────────────────────────
echo ""
echo "=== Integration Test Complete ==="
echo "Reports:  $REPORT_DIR"
echo "DB backup: $BACKUP"
echo ""
echo "To restore DB, run: engrammar restore"
echo ""
ls -la "$REPORT_DIR"/
