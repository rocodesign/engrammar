# src/ Reorganization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize 18 flat modules in src/ into 4 subdirectories (core/, search/, pipeline/, infra/) for navigability.

**Architecture:** Move files into subdirectories, update all relative imports within src/ to cross-subpackage paths, update all `from engrammar.X` imports in hooks/cli/tests/backfill to `from engrammar.subpkg.X`, update deploy/setup scripts and conftest.py.

**Tech Stack:** Python, bash

---

### Task 1: Create subdirectory structure and move files

**Files:**
- Create: `src/core/__init__.py`, `src/search/__init__.py`, `src/pipeline/__init__.py`, `src/infra/__init__.py`
- Move: all 17 .py modules into their subdirectories

**Step 1: Create subdirectories with empty `__init__.py` files**

```bash
mkdir -p src/core src/search src/pipeline src/infra
touch src/core/__init__.py src/search/__init__.py src/pipeline/__init__.py src/infra/__init__.py
```

**Step 2: Move files via git mv**

```bash
# core/
git mv src/config.py src/core/config.py
git mv src/db.py src/core/db.py
git mv src/embeddings.py src/core/embeddings.py
git mv src/prompt_loader.py src/core/prompt_loader.py

# search/ (search.py → engine.py rename)
git mv src/search.py src/search/engine.py
git mv src/environment.py src/search/environment.py
git mv src/tag_detectors.py src/search/tag_detectors.py
git mv src/tag_patterns.py src/search/tag_patterns.py

# pipeline/
git mv src/extractor.py src/pipeline/extractor.py
git mv src/evaluator.py src/pipeline/evaluator.py
git mv src/dedup.py src/pipeline/dedup.py

# infra/
git mv src/daemon.py src/infra/daemon.py
git mv src/client.py src/infra/client.py
git mv src/hook_utils.py src/infra/hook_utils.py
git mv src/mcp_server.py src/infra/mcp_server.py
git mv src/register_hooks.py src/infra/register_hooks.py
```

**Step 3: Commit**

```bash
git add src/core/ src/search/ src/pipeline/ src/infra/
git commit -m "chore: move src/ modules into subdirectories (imports not yet updated)"
```

---

### Task 2: Update relative imports within src/ modules

Each module that uses relative imports (`.config`, `.db`, etc.) needs updating to cross-subpackage absolute imports.

**Files to modify:**
- `src/core/db.py` — `from .config` → `from .config` (stays same, same subpackage)
- `src/core/embeddings.py` — `from .config` → `from .config` (stays same)
- `src/search/engine.py` — 4 imports to update
- `src/search/environment.py` — 1 import to update
- `src/search/tag_detectors.py` — `from .tag_patterns` → stays same
- `src/pipeline/extractor.py` — 3 imports to update
- `src/pipeline/evaluator.py` — 2 imports to update
- `src/pipeline/dedup.py` — 3 imports to update

**Step 1: Update `src/search/engine.py` (was search.py)**

Change:
```python
from .config import LAST_SEARCH_PATH, load_config
from .db import get_all_active_engrams
from .embeddings import embed_text, load_index, load_tag_index, vector_search
from .environment import detect_environment
```
To:
```python
from engrammar.core.config import LAST_SEARCH_PATH, load_config
from engrammar.core.db import get_all_active_engrams
from engrammar.core.embeddings import embed_text, load_index, load_tag_index, vector_search
from .environment import detect_environment
```

**Step 2: Update `src/search/environment.py`**

Change:
```python
from .tag_detectors import detect_tags
```
Stays the same — same subpackage.

**Step 3: Update `src/pipeline/extractor.py`**

Change:
```python
from .db import (...)
from .embeddings import build_index, embed_batch
from .prompt_loader import load_prompt
```
To:
```python
from engrammar.core.db import (...)
from engrammar.core.embeddings import build_index, embed_batch
from engrammar.core.prompt_loader import load_prompt
```

**Step 4: Update `src/pipeline/evaluator.py`**

Change:
```python
from .db import get_connection, get_unprocessed_audit_sessions
from .prompt_loader import load_prompt
```
To:
```python
from engrammar.core.db import get_connection, get_unprocessed_audit_sessions
from engrammar.core.prompt_loader import load_prompt
```

**Step 5: Update `src/pipeline/dedup.py`**

Change:
```python
from .db import (...)
from .embeddings import embed_batch, build_index, build_tag_index
from .prompt_loader import load_prompt
```
To:
```python
from engrammar.core.db import (...)
from engrammar.core.embeddings import embed_batch, build_index, build_tag_index
from engrammar.core.prompt_loader import load_prompt
```

**Step 6: Verify no relative imports are broken**

```bash
grep -rn "^from \." src/ | grep -v __pycache__
```

Remaining relative imports should only be within the same subpackage:
- `src/core/db.py`: `from .config`
- `src/core/embeddings.py`: `from .config`
- `src/search/engine.py`: `from .environment`
- `src/search/tag_detectors.py`: `from .tag_patterns`

**Step 7: Commit**

```bash
git add -A src/
git commit -m "chore: update relative imports for new subdirectory structure"
```

---

### Task 3: Update lazy imports in daemon.py and mcp_server.py

These use `from engrammar.X` inside functions — all need subpackage paths.

**Files:**
- Modify: `src/infra/daemon.py`
- Modify: `src/infra/mcp_server.py`

**Step 1: Update `src/infra/daemon.py`**

Apply these replacements:
```
from engrammar.embeddings     → from engrammar.core.embeddings
from engrammar.search         → from engrammar.search.engine
from engrammar.db             → from engrammar.core.db
from engrammar.environment    → from engrammar.search.environment
```

**Step 2: Update `src/infra/mcp_server.py`**

Apply these replacements:
```
from engrammar.search import search      → from engrammar.search.engine import search
from engrammar.db                        → from engrammar.core.db
from engrammar.embeddings                → from engrammar.core.embeddings
from engrammar.hook_utils                → from engrammar.infra.hook_utils
from engrammar.environment               → from engrammar.search.environment
from engrammar.config                    → from engrammar.core.config
```

**Step 3: Commit**

```bash
git add src/infra/daemon.py src/infra/mcp_server.py
git commit -m "chore: update lazy imports in daemon and mcp_server"
```

---

### Task 4: Update imports in hooks/

All 4 hook files use `from engrammar.X` lazy imports.

**Files:**
- Modify: `hooks/on_session_start.py`
- Modify: `hooks/on_prompt.py`
- Modify: `hooks/on_tool_use.py`
- Modify: `hooks/on_stop.py`

**Step 1: Apply import mapping to all hook files**

```
from engrammar.hook_utils    → from engrammar.infra.hook_utils
from engrammar.client        → from engrammar.infra.client
from engrammar.config        → from engrammar.core.config
from engrammar.db            → from engrammar.core.db
from engrammar.search        → from engrammar.search.engine
from engrammar.extractor     → from engrammar.pipeline.extractor
from engrammar.environment   → from engrammar.search.environment
```

**Step 2: Commit**

```bash
git add hooks/
git commit -m "chore: update hook imports for src/ reorganization"
```

---

### Task 5: Update imports in cli.py and backfill_stats.py

**Files:**
- Modify: `cli.py`
- Modify: `backfill_stats.py`

**Step 1: Update `cli.py`**

Apply mapping:
```
from engrammar.config       → from engrammar.core.config
from engrammar.db           → from engrammar.core.db
from engrammar.embeddings   → from engrammar.core.embeddings
from engrammar.search       → from engrammar.search.engine
from engrammar.extractor    → from engrammar.pipeline.extractor
from engrammar.evaluator    → from engrammar.pipeline.evaluator
from engrammar.environment  → from engrammar.search.environment
from engrammar.tag_detectors → from engrammar.search.tag_detectors
from engrammar.dedup        → from engrammar.pipeline.dedup
```

**Step 2: Update `backfill_stats.py`**

Apply mapping:
```
from engrammar.tag_patterns  → from engrammar.search.tag_patterns
from engrammar.db            → from engrammar.core.db
from engrammar.search        → from engrammar.search.engine
from engrammar.evaluator     → from engrammar.pipeline.evaluator
```

**Step 3: Commit**

```bash
git add cli.py backfill_stats.py
git commit -m "chore: update cli.py and backfill_stats.py imports"
```

---

### Task 6: Update tests/conftest.py module aliasing

The test conftest creates `sys.modules["engrammar.X"]` aliases. These need to map to the new subpackage paths.

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Rewrite conftest.py module aliasing**

Replace the current aliasing block with:

```python
import src
import src.core.config
import src.core.db
import src.core.embeddings
import src.core.prompt_loader
import src.search.engine
import src.search.environment
import src.search.tag_detectors
import src.search.tag_patterns
import src.pipeline.extractor
import src.pipeline.evaluator
import src.pipeline.dedup
import src.infra.hook_utils
import src.infra.client
import src.infra.daemon
import src.infra.mcp_server
import src.infra.register_hooks

sys.modules["engrammar"] = src
# Map subpackages
sys.modules["engrammar.core"] = src.core
sys.modules["engrammar.search"] = src.search
sys.modules["engrammar.pipeline"] = src.pipeline
sys.modules["engrammar.infra"] = src.infra
# Map individual modules
for subpkg, modules in {
    "core": ["config", "db", "embeddings", "prompt_loader"],
    "search": ["engine", "environment", "tag_detectors", "tag_patterns"],
    "pipeline": ["extractor", "evaluator", "dedup"],
    "infra": ["hook_utils", "client", "daemon", "mcp_server", "register_hooks"],
}.items():
    for mod in modules:
        sys.modules[f"engrammar.{subpkg}.{mod}"] = getattr(getattr(src, subpkg), mod)
```

Also update the fixture references:
```python
from src.core import config, db
from src.core.db import init_db
```

And the mock_build_index fixture:
```python
monkeypatch.setattr("src.core.embeddings.build_index", lambda *a, **kw: 0)
```

**Step 2: Run tests**

```bash
bash scripts/run_tests.sh
```

Expected: All tests pass (except the pre-existing test_truncates_to_max_chars failure).

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: update test conftest for new src/ subpackage structure"
```

---

### Task 7: Update deploy and setup scripts

The deploy script copies `src/*.py` flat — needs to copy subdirectories. Setup script copies `src` as a tree (already works).

**Files:**
- Modify: `scripts/deploy.sh`
- Modify: `scripts/setup.sh` (verify — may already work)

**Step 1: Update `scripts/deploy.sh`**

Replace:
```bash
# Copy source package
echo "  src/ -> engrammar/"
rm -rf "$ENGRAMMAR_HOME/engrammar/__pycache__"
cp "$SOURCE_DIR"/src/*.py "$ENGRAMMAR_HOME/engrammar/"
```

With:
```bash
# Copy source package
echo "  src/ -> engrammar/"
rm -rf "$ENGRAMMAR_HOME/engrammar"
cp -r "$SOURCE_DIR/src" "$ENGRAMMAR_HOME/engrammar"
find "$ENGRAMMAR_HOME/engrammar" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

**Step 2: Verify `scripts/setup.sh`**

The setup script already does `cp -r "$SOURCE_DIR/src" "$ENGRAMMAR_HOME/engrammar"` — this copies the full tree, so it already works. No change needed.

**Step 3: Test deploy**

```bash
bash scripts/deploy.sh
```

Expected: "Deployed." with no errors.

**Step 4: Verify deployed structure**

```bash
ls ~/.engrammar/engrammar/core/ ~/.engrammar/engrammar/search/ ~/.engrammar/engrammar/pipeline/ ~/.engrammar/engrammar/infra/
```

Expected: All module files present in subdirectories.

**Step 5: Commit**

```bash
git add scripts/deploy.sh
git commit -m "chore: update deploy script for src/ subdirectory structure"
```

---

### Task 8: Update register_hooks.py path reference

The setup script runs `register_hooks.py` from the deployed location. Verify the path still resolves after the move.

**Files:**
- Check: `scripts/setup.sh` line 92
- Check: `scripts/install.sh` line 291

**Step 1: Verify path**

Both scripts call:
```bash
"$VENV_BIN/python" "$ENGRAMMAR_HOME/engrammar/register_hooks.py"
```

After reorganization, the file is at `$ENGRAMMAR_HOME/engrammar/infra/register_hooks.py`. Update both scripts:

```bash
"$VENV_BIN/python" "$ENGRAMMAR_HOME/engrammar/infra/register_hooks.py"
```

**Step 2: Commit**

```bash
git add scripts/setup.sh scripts/install.sh
git commit -m "fix: update register_hooks.py path for new subdirectory"
```

---

### Task 9: Update documentation

**Files:**
- Modify: `docs/CHEATSHEET.md` (file tree section around line 631)
- Modify: `docs/ARCHITECTURE.md` (if it references src/ file paths)

**Step 1: Update CHEATSHEET.md deployed file tree**

Update the `~/.engrammar/` file tree to reflect subdirectories:
```
├── engrammar/
│   ├── core/               # Foundation: config, db, embeddings
│   ├── search/             # Search pipeline + environment detection
│   ├── pipeline/           # Extraction, evaluation, dedup
│   └── infra/              # Daemon, client, MCP server, hooks
```

**Step 2: Check ARCHITECTURE.md for path references**

```bash
grep -n "src/" docs/ARCHITECTURE.md
```

Update any references to flat src/ paths.

**Step 3: Commit**

```bash
git add docs/
git commit -m "docs: update file references for src/ reorganization"
```

---

### Task 10: Final verification

**Step 1: Deploy and verify**

```bash
bash scripts/deploy.sh
engrammar status
```

Expected: Status output with no errors.

**Step 2: Run tests**

```bash
bash scripts/run_tests.sh
```

Expected: All tests pass (except pre-existing test_truncates_to_max_chars).

**Step 3: Grep for stale imports**

```bash
grep -rn "from engrammar\.\(config\|db\|embeddings\|search\|environment\|hook_utils\|client\|tag_patterns\|tag_detectors\|prompt_loader\|extractor\|evaluator\|dedup\|daemon\|mcp_server\|register_hooks\) " --include="*.py" . | grep -v __pycache__ | grep -v issues/
```

Expected: Zero results — all imports should use subpackage paths now.

**Step 4: Squash into clean commit (optional)**

```bash
git rebase -i HEAD~9
```

Squash into a single commit: `refactor: reorganize src/ into core/, search/, pipeline/, infra/ subdirectories`
