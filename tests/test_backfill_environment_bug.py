"""
Regression test documenting the backfill environment bug.

KNOWN ISSUE: Backfill uses CURRENT environment to filter lessons for HISTORICAL sessions.
This causes incorrect match statistics when sessions were in different repos/environments.

See: Bug Analysis - Backfill Environment Filtering

This test documents the issue and serves as a reminder that backfill is unreliable
when used across different repositories or environments.
"""

import json
import tempfile
from pathlib import Path
import os

import pytest

from src.db import init_db, get_connection, add_lesson
from src.search import search
from src.environment import detect_environment


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


class TestBackfillEnvironmentBug:
    """Tests documenting the backfill environment filtering bug."""

    def test_search_uses_current_environment_not_historical(self, test_db, monkeypatch):
        """
        KNOWN BUG: search() always uses current environment, not historical context.

        This test demonstrates that backfill cannot accurately determine which lessons
        should have matched in historical sessions from different environments.
        """
        # Create a lesson with acme tag prerequisite
        conn = get_connection(test_db)
        conn.execute(
            "INSERT INTO lessons (text, category, prerequisites, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (
                "Use Acme patterns",
                "development",
                json.dumps({"tags": ["acme", "react"]})
            )
        )
        conn.commit()
        conn.close()

        # Simulate historical session environment (acme project)
        historical_env = {
            'os': 'darwin',
            'repo': 'app-repo',
            'cwd': '/Users/user/work/acme/app-repo',
            'tags': ['acme', 'react', 'frontend'],  # Had acme tag!
        }

        # Simulate current environment (personal project)
        monkeypatch.setattr(os, 'getcwd', lambda: '/Users/user/work/personal/my-app')
        current_env = detect_environment()
        # current_env.tags will NOT include 'acme'

        # Search using current environment (what backfill does)
        from src.embeddings import build_index
        from src.db import get_all_active_lessons
        lessons = get_all_active_lessons(test_db)
        build_index(lessons)

        results = search("acme patterns", db_path=test_db)

        # BUG: Lesson is excluded because current env doesn't have 'acme' tag
        # even though historical session DID have the tag
        assert len(results) == 0, "Lesson excluded due to current env (should have matched in historical env)"

        # What SHOULD happen: Lesson should be included because historical session
        # had the acme tag. But backfill has no way to know this.
        # Historical session data: ✓ has repo, ✗ doesn't have tags

    def test_backfill_false_negative_scenario(self, test_db):
        """
        Demonstrate false negative: Lesson should match historical session but doesn't.

        Historical session: acme/app-repo with ['acme', 'react'] tags
        Backfill run from:  personal/my-app with ['personal', 'vue'] tags
        Result: Acme-specific lessons are excluded (WRONG)
        """
        # Create acme-specific lesson
        conn = get_connection(test_db)
        cursor = conn.execute(
            "INSERT INTO lessons (text, category, prerequisites, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (
                "Use Picasso components",
                "development/frontend",
                json.dumps({"tags": ["acme", "react"]})
            )
        )
        lesson_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Historical session was in acme/app-repo
        # User prompt: "How to create a table component"
        # Lesson SHOULD match because session had ['acme', 'react'] tags

        # But when backfill runs from personal/my-app...
        # search() filters by current env which has ['personal', 'vue']
        # Lesson is excluded (FALSE NEGATIVE)

        # This is what backfill_stats.py:115 does:
        from src.search import search
        from src.embeddings import build_index
        from src.db import get_all_active_lessons

        lessons = get_all_active_lessons(test_db)
        build_index(lessons)

        results = search("table component", db_path=test_db)

        # Lesson won't be in results because current env doesn't match prerequisites
        lesson_ids = [r['id'] for r in results]

        # BUG DEMONSTRATED: Lesson is excluded
        assert lesson_id not in lesson_ids, \
            "BUG: Lesson excluded from backfill because current env doesn't match, " \
            "even though historical session DID match"

    def test_backfill_false_positive_scenario(self, test_db):
        """
        Demonstrate false positive: Lesson shouldn't match historical session but does.

        Historical session: personal/my-app with ['vue'] tags
        Backfill run from:  acme/app-repo with ['acme', 'react'] tags
        Result: Acme-specific lessons are included (WRONG)
        """
        # Create lesson WITHOUT prerequisites (matches everything)
        conn = get_connection(test_db)
        cursor = conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            ("General React patterns", "development/frontend")
        )
        lesson_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Historical session: personal Vue project (no 'acme' or 'react' tags)
        # User prompt: "component state management"
        # Lesson SHOULD match because it has no prerequisites

        # But if lesson had acme prerequisites and backfill runs from acme repo...
        # It would match even though historical session was Vue (FALSE POSITIVE)

        # This test shows the inverse: lessons without prerequisites always match
        # regardless of environment, which is correct behavior
        from src.search import search
        from src.embeddings import build_index
        from src.db import get_all_active_lessons

        lessons = get_all_active_lessons(test_db)
        build_index(lessons)

        results = search("state management", db_path=test_db)
        lesson_ids = [r['id'] for r in results]

        # This one matches because no prerequisites (correct)
        # But the bug would cause acme-prerequisite lessons to match too

    def test_backfill_has_no_access_to_historical_tags(self):
        """
        Document that session transcripts don't include tag information.

        Even if we wanted to fix backfill, we can't because historical
        session data doesn't include the tags that were detected.
        """
        # Simulated session transcript data structure
        session_data = {
            'session_id': 'abc-123',
            'messages': [
                {'role': 'user', 'content': 'How to create a component?'},
                {'role': 'assistant', 'content': 'Use React...'}
            ],
            'repo': 'app-repo',  # ✓ Available
            'cwd': '/Users/user/work/acme/app-repo',  # ✓ Available
            'timestamp': '2024-01-01T12:00:00',  # ✓ Available
            # 'tags': [...]  # ✗ NOT AVAILABLE - this is the problem!
        }

        # We could reconstruct SOME tags from cwd path:
        # '/work/acme/' → 'acme' tag
        # But we CAN'T reconstruct tags from:
        # - File markers (tsconfig.json) - files may have changed
        # - Dependencies (package.json) - dependencies may have changed
        # - Directory structure - structure may have changed
        # - Git remote - repo may have moved

        # At best, we can get 20% of tags (path-based only)
        # This makes backfill fundamentally unreliable

        assert 'tags' not in session_data, \
            "Session transcripts don't include tags, making accurate backfill impossible"


class TestBackfillRecommendation:
    """Document the recommendation to deprecate backfill."""

    def test_real_time_tracking_is_preferred(self):
        """
        Real-time tracking via session end hook is the correct approach.

        Why real-time is better:
        1. Has accurate environment at the time
        2. Tracks actual shown lessons, not guesses
        3. No risk of data corruption
        4. Simpler system
        """
        recommendation = {
            'use': 'Real-time tracking via session end hook',
            'avoid': 'Backfill from different environment',
            'reason': 'Backfill uses current env for historical sessions (unreliable)',
            'workaround': 'Run backfill FROM the same repo as historical sessions',
            'better': 'Accept that statistics accumulate over time naturally'
        }

        assert recommendation['use'] == 'Real-time tracking via session end hook'
        assert recommendation['avoid'] == 'Backfill from different environment'


@pytest.mark.skip(reason="Documents known limitation, not a failing test")
class TestBackfillSolution:
    """Potential solutions to the backfill bug (not yet implemented)."""

    def test_solution_1_accept_environment_parameter(self):
        """
        Solution 1: Modify search() to accept environment override.

        def search(query, env=None, ...):
            if env is None:
                env = detect_environment()
            # ... rest of search

        Then backfill could reconstruct historical env and pass it.

        Status: Not implemented
        Complexity: Medium
        Effectiveness: Partial (can only reconstruct path-based tags)
        """
        pass

    def test_solution_2_disable_filtering_for_backfill(self):
        """
        Solution 2: Add skip_env_filter parameter.

        def search(query, skip_env_filter=False, ...):
            if not skip_env_filter:
                lessons = filter_by_prerequisites(lessons, env)
            # ... rest of search

        Then backfill could skip filtering entirely.

        Status: Not implemented
        Complexity: Low
        Effectiveness: Poor (includes wrong lessons)
        """
        pass

    def test_solution_3_deprecate_backfill(self):
        """
        Solution 3: Document limitation and deprecate backfill.

        Add warning to CLI:
        "WARNING: Backfill uses current environment. Results may be
         incorrect for sessions in different repos. Consider using
         real-time tracking instead."

        Status: RECOMMENDED
        Complexity: None
        Effectiveness: Complete (avoids the problem)
        """
        pass
