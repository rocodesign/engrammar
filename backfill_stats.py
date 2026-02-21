#!/usr/bin/env python3
"""Backfill session audit records from past Claude Code transcripts.

Reads session transcripts, identifies which engrams would have been shown,
and creates session_audit records for the evaluator pipeline to process.

Does NOT directly update match stats — evaluation is handled by
`engrammar evaluate` which sends transcripts to Haiku for quality scoring.
"""

import json
import os
import sys
import glob
from datetime import datetime
from pathlib import Path

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)



def find_session_files(projects_dir=None):
    """Find all session JSONL files in Claude Code projects directory."""
    if projects_dir is None:
        projects_dir = os.path.expanduser("~/.claude/projects")

    if not os.path.exists(projects_dir):
        return []

    # Find all .jsonl files in project subdirectories
    pattern = os.path.join(projects_dir, "*", "*.jsonl")
    return sorted(glob.glob(pattern))


def read_session_transcript(jsonl_path):
    """Read a session transcript and extract user prompts and assistant responses.

    Returns:
        dict: {
            'session_id': str,
            'messages': [{'role': 'user'|'assistant', 'content': str}, ...],
            'repo': str or None,
            'cwd': str or None,
            'timestamp': str
        }
    """
    messages = []
    repo = None
    cwd = None
    timestamp = None

    try:
        with open(jsonl_path, 'r') as f:
            for line in f:
                if not line.strip():
                    continue

                entry = json.loads(line)
                entry_type = entry.get('type')

                # Extract cwd/repo from any entry
                if not cwd and 'cwd' in entry:
                    cwd = entry['cwd']
                    # Extract repo name from path
                    if '/work/' in cwd:
                        parts = cwd.split('/work/')[-1].split('/')
                        if parts:
                            repo = parts[0]

                # Extract timestamp
                if not timestamp and 'timestamp' in entry:
                    timestamp = entry['timestamp']

                # Only process user and assistant message entries
                if entry_type not in ('user', 'assistant'):
                    continue

                # Extract message content
                message_obj = entry.get('message', {})
                role = message_obj.get('role')
                content = message_obj.get('content', '')

                if not role or not content:
                    continue

                # Extract text content
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get('type') == 'text':
                            text_parts.append(part.get('text', ''))
                    content = ' '.join(text_parts)
                elif isinstance(content, str):
                    pass  # Already a string
                else:
                    continue

                messages.append({'role': role, 'content': content})

    except Exception as e:
        print(f"Error reading {jsonl_path}: {e}")
        return None

    session_id = os.path.basename(jsonl_path).replace('.jsonl', '')

    return {
        'session_id': session_id,
        'messages': messages,
        'repo': repo,
        'cwd': cwd,
        'timestamp': timestamp or datetime.now().isoformat()
    }


def _infer_env_from_transcript(session_data):
    """Infer environment tags from transcript data (best-effort).

    Uses GIT_REMOTE_PATTERNS from the tag detection system applied against
    the transcript's git remote info.

    Returns:
        list of tag strings
    """
    from engrammar.tag_patterns import GIT_REMOTE_PATTERNS

    tags = set()

    git_remote = session_data.get('git_remote', '') or ''
    if git_remote:
        for pattern, tag in GIT_REMOTE_PATTERNS:
            if pattern.search(git_remote):
                tags.add(tag)

    return sorted(tags)


def _has_existing_audit(session_id, db_path=None):
    """Check if a session_audit record already exists."""
    from engrammar.db import get_connection

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT 1 FROM session_audit WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row is not None


def backfill_session(session_data, dry_run=False, verbose=False, db_path=None):
    """Create a session_audit record for a historical session.

    Searches for engrams that would have been shown (without prerequisite
    filtering) and records them as an audit entry for the evaluator pipeline.

    Args:
        session_data: Session transcript data
        dry_run: Don't update database
        verbose: Show per-engram details
        db_path: optional database path

    Returns:
        dict: {'shown': int, 'audit_created': bool, 'engram_ids': [ids]}
    """
    from engrammar.search import search

    session_id = session_data['session_id']

    # Skip if audit record already exists
    if not dry_run and _has_existing_audit(session_id, db_path=db_path):
        return {'shown': 0, 'audit_created': False, 'engram_ids': [], 'skipped': 'already_audited'}

    messages = session_data['messages']
    repo = session_data['repo']

    # Collect all user prompts
    user_prompts = [msg['content'] for msg in messages if msg['role'] == 'user']

    if not user_prompts:
        return {'shown': 0, 'audit_created': False, 'engram_ids': []}

    # Find engrams that would have been shown (skip prerequisite filtering
    # since we can't reconstruct the historical environment accurately)
    all_engrams = {}
    for prompt in user_prompts:
        if len(prompt) < 5:
            continue

        try:
            results = search(prompt, top_k=5, db_path=db_path, skip_prerequisites=True)
            for engram in results:
                if engram['id'] not in all_engrams:
                    all_engrams[engram['id']] = engram
        except Exception as e:
            if verbose:
                print(f"    Search error: {e}")

    if not all_engrams:
        return {'shown': 0, 'audit_created': False, 'engram_ids': []}

    engram_ids = sorted(all_engrams.keys())

    if verbose:
        for lid in engram_ids:
            print(f"    Engram #{lid}: {all_engrams[lid]['text'][:60]}...")

    if not dry_run:
        from engrammar.db import write_session_audit

        env_tags = _infer_env_from_transcript(session_data)
        write_session_audit(session_id, engram_ids, env_tags, repo, db_path=db_path)

    return {'shown': len(all_engrams), 'audit_created': True, 'engram_ids': engram_ids}


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Create session audit records from past Claude Code transcripts. "
                    "Records are processed by `engrammar evaluate` for quality scoring."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without updating DB")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-engram details")
    parser.add_argument("--limit", type=int, help="Process only N most recent sessions")
    parser.add_argument("--session", help="Process a specific session file")
    parser.add_argument("--projects-dir", help="Override projects directory (default: ~/.claude/projects)")
    parser.add_argument("--evaluate", action="store_true",
                        help="Also run evaluator after creating audit records")

    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN MODE - no database changes will be made\n")

    # Find session files
    if args.session:
        session_files = [args.session]
    else:
        session_files = find_session_files(args.projects_dir)
        if args.limit:
            session_files = session_files[-args.limit:]  # Most recent N

    if not session_files:
        print("No session files found")
        return

    print(f"Found {len(session_files)} session(s) to process\n")

    # Process each session
    audits_created = 0
    already_audited = 0
    no_engrams = 0
    skipped = 0

    for i, session_file in enumerate(session_files, 1):
        print(f"[{i}/{len(session_files)}] {os.path.basename(session_file)}...")

        session_data = read_session_transcript(session_file)
        if not session_data:
            print("  Skipped (read error)")
            skipped += 1
            continue

        if not session_data['messages']:
            print("  Skipped (no messages)")
            skipped += 1
            continue

        result = backfill_session(session_data, dry_run=args.dry_run, verbose=args.verbose)

        if result.get('skipped') == 'already_audited':
            print("  Already audited")
            already_audited += 1
        elif result['shown'] == 0:
            print("  No matching engrams")
            no_engrams += 1
        else:
            action = "Would create" if args.dry_run else "Created"
            print(f"  {action} audit: {result['shown']} engrams, repo={session_data['repo'] or 'unknown'}")
            audits_created += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Backfill complete")
    print(f"{'='*60}")
    print(f"Audit records created: {audits_created}")
    print(f"Already audited:       {already_audited}")
    print(f"No matching engrams:   {no_engrams}")
    print(f"Skipped (errors):      {skipped}")

    if args.dry_run:
        print("\nDRY RUN - no changes were made.")
    elif audits_created > 0:
        print(f"\nRun `engrammar evaluate` to process these audit records through Haiku.")

    # Optionally run evaluator
    if args.evaluate and not args.dry_run and audits_created > 0:
        print("\nRunning evaluator...")
        from engrammar.evaluator import run_pending_evaluations

        results = run_pending_evaluations(limit=audits_created)
        print(f"  Completed: {results['completed']}")
        print(f"  Failed:    {results['failed']}")


if __name__ == "__main__":
    main()
