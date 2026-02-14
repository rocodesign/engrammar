#!/usr/bin/env python3
"""Backfill lesson match statistics by analyzing past Claude Code sessions.

Reads session transcripts, identifies which lessons would have been shown,
and uses Haiku to evaluate if they were actually useful.
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
            'timestamp': str
        }
    """
    messages = []
    repo = None
    timestamp = None

    try:
        with open(jsonl_path, 'r') as f:
            for line in f:
                if not line.strip():
                    continue

                entry = json.loads(line)
                entry_type = entry.get('type')

                # Extract cwd/repo from any entry
                if not repo and 'cwd' in entry:
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
        'timestamp': timestamp or datetime.now().isoformat()
    }


def find_relevant_lessons(prompt, db_path=None):
    """Find lessons that would have been shown for this prompt."""
    from engrammar.search import search

    try:
        return search(prompt, top_k=5, db_path=db_path)
    except Exception as e:
        print(f"Error searching lessons: {e}")
        return []


def evaluate_lesson_in_session(lesson, session_messages):
    """Use Haiku to evaluate if a lesson was useful in a session.

    Args:
        lesson: dict with lesson data
        session_messages: list of message dicts with 'role' and 'content'

    Returns:
        bool: True if lesson was useful
    """
    import anthropic

    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        claude_config_path = os.path.expanduser("~/.claude.json")
        if os.path.exists(claude_config_path):
            with open(claude_config_path, "r") as f:
                config = json.load(f)
                api_key = config.get("apiKey")

    if not api_key:
        print("Warning: No ANTHROPIC_API_KEY found, assuming all lessons useful")
        return True

    # Build session summary (first and last few messages)
    summary_parts = []
    if len(session_messages) > 0:
        summary_parts.append("Session start:")
        for msg in session_messages[:3]:
            role = msg['role']
            content = msg['content'][:200]  # Truncate
            summary_parts.append(f"{role}: {content}")

    if len(session_messages) > 6:
        summary_parts.append("...")
        summary_parts.append("Session end:")
        for msg in session_messages[-3:]:
            role = msg['role']
            content = msg['content'][:200]
            summary_parts.append(f"{role}: {content}")

    session_summary = "\n".join(summary_parts)

    try:
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""You are evaluating whether a lesson was useful during a Claude Code session.

Lesson: [{lesson.get('category', 'general')}] {lesson['text']}

Session transcript excerpt:
{session_summary}

Was this lesson actually relevant and useful during this session? Consider:
- Did the assistant follow this lesson's guidance?
- Did the lesson prevent an error or guide correct behavior?
- Was the topic of the lesson even relevant to what was done?

Answer only: YES or NO"""

        response = client.messages.create(
            model="claude-haiku-4.5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = response.content[0].text.strip().upper()
        return answer == "YES"

    except Exception as e:
        print(f"Error evaluating lesson {lesson['id']}: {e}")
        return False  # Fail closed on errors


def backfill_session(session_data, dry_run=False, verbose=False):
    """Analyze a session and update match stats for useful lessons.

    Returns:
        dict: {'shown': int, 'useful': int, 'lessons': [ids]}
    """
    from engrammar.db import update_match_stats

    messages = session_data['messages']
    repo = session_data['repo']

    # Collect all user prompts
    user_prompts = [msg['content'] for msg in messages if msg['role'] == 'user']

    if not user_prompts:
        return {'shown': 0, 'useful': 0, 'lessons': []}

    # Find lessons that would have been shown
    all_lessons = {}
    for prompt in user_prompts:
        if len(prompt) < 5:
            continue

        results = find_relevant_lessons(prompt)
        for lesson in results:
            if lesson['id'] not in all_lessons:
                all_lessons[lesson['id']] = lesson

    if not all_lessons:
        return {'shown': 0, 'useful': 0, 'lessons': []}

    # Evaluate each lesson
    useful_lessons = []
    for lesson_id, lesson in all_lessons.items():
        is_useful = evaluate_lesson_in_session(lesson, messages)

        if verbose:
            status = "✓ useful" if is_useful else "✗ not useful"
            print(f"  Lesson {lesson_id}: {status}")

        if is_useful:
            useful_lessons.append(lesson_id)
            if not dry_run:
                update_match_stats(lesson_id, repo=repo)

    return {
        'shown': len(all_lessons),
        'useful': len(useful_lessons),
        'lessons': useful_lessons
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Backfill lesson statistics from past sessions")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without updating DB")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed per-lesson evaluation")
    parser.add_argument("--limit", type=int, help="Process only N most recent sessions")
    parser.add_argument("--session", help="Process a specific session file")
    parser.add_argument("--projects-dir", help="Override projects directory (default: ~/.claude/projects)")

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

    print(f"Found {len(session_files)} session(s) to analyze\n")

    # Process each session
    total_shown = 0
    total_useful = 0
    processed = 0
    skipped = 0

    for i, session_file in enumerate(session_files, 1):
        print(f"[{i}/{len(session_files)}] Processing {os.path.basename(session_file)}...")

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

        if result['shown'] == 0:
            print(f"  No lessons shown")
        else:
            print(f"  Shown: {result['shown']}, Useful: {result['useful']}, Repo: {session_data['repo'] or 'unknown'}")

        total_shown += result['shown']
        total_useful += result['useful']
        processed += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Backfill complete")
    print(f"{'='*60}")
    print(f"Sessions processed: {processed}")
    print(f"Sessions skipped:   {skipped}")
    print(f"Lessons shown:      {total_shown}")
    print(f"Lessons useful:     {total_useful}")

    if total_shown > 0:
        usefulness_rate = (total_useful / total_shown) * 100
        print(f"Usefulness rate:    {usefulness_rate:.1f}%")

    if args.dry_run:
        print("\nDRY RUN - no changes were made. Run without --dry-run to update stats.")


if __name__ == "__main__":
    main()
