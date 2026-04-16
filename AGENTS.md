In this repo refrain from using engrammar mcp, we are developing engrammar here and we want to determine how to automatically improve learning rather than just fixing the db state.

## Deployment

- **First install**: `bash scripts/setup.sh` — creates venv, copies files, initializes DB, registers hooks
- **After code changes**: `bash scripts/deploy.sh` — copies src/, hooks/, cli.py to `~/.engrammar/`
- **With daemon restart**: `bash scripts/deploy.sh --restart`

## Tracking Work

Don't let ideas stay only in conversation — if it's worth discussing, it's worth writing down.

Tasks, bugs, and ideas are tracked in both **local files** and **[GitHub Issues](https://github.com/rocodesign/engrammar/issues)**. Keep both in sync.

### Local tracking

| Type | Location | Naming | Index |
|------|----------|--------|-------|
| Bugs, design flaws | `issues/open/` | `[severity]-NNN-slug/issue.md` | `issues/ISSUES.md` |
| Features, planned work | `tasks/open/` | `[priority]-NNN-slug/task.md` | `tasks/tasks.md` |
| Completed tasks | `tasks/completed/` | `[priority]-NNN-slug/task.md` | `tasks/tasks.md` |
| Resolved issues | `issues/resolved/` | `[severity]-NNN-slug/issue.md` | `issues/ISSUES.md` |
| Loose ideas | `tasks/ideas/` | `descriptive-name.md` | listed in `tasks/tasks.md` |

- **Issues** use severity: `[1]` Critical, `[2]` High, `[3]` Medium, `[4]` Low
- **Tasks** use priority: `[1]` High, `[2]` Medium, `[3]` Low
- Both use complexity: `C1` low-hanging, `C2` medium, `C3` high

### GitHub Issues labels

| Label | Use for |
|-------|---------|
| `task` | Features, planned work |
| `bug` | Bugs, design flaws |
| `idea` | Loose ideas needing more thought |
| `priority:1-critical` | Blocks other work or degrades core functionality |
| `priority:2-high` | Improves quality but system works without it |
| `priority:3-medium` | Nice to have |
| `priority:4-low` | Low priority |

### When to capture

- Discussing a new feature or improvement? Create both a local task file and a GitHub issue with the `task` label.
- Found a bug or design flaw? Create both a local issue file and a GitHub issue with the `bug` label.
- Have a vague idea that needs more thought? Create both a local idea file and a GitHub issue with the `idea` label.
- If something is both a bug and needs feature work, create an issue for the problem and reference it from the task.

### Workflow

1. During conversation, identify things worth tracking.
2. Create the local folder + markdown file in the right location.
3. Create a matching GitHub issue with appropriate labels.
4. Update the corresponding index file (`ISSUES.md` or `tasks.md`).
5. When starting work on a task/issue, note it in both the local file and the GitHub issue.
6. When done, move local issues to `issues/resolved/` and tasks to `tasks/completed/`, close the GitHub issue, and update the index.

## Documentation

Update documentation after every task or change. Don't defer doc updates to later sessions.

- **Architecture changes**: Update `docs/ARCHITECTURE.md` and the [wiki](https://github.com/rocodesign/engrammar/wiki)
- **New/changed CLI commands**: Update `docs/CLI.md` and `docs/CHEATSHEET.md`
- **Config changes**: Update `docs/CONFIG.md`
- **Pipeline changes**: Update `docs/ARCHITECTURE.md` (pipeline sections)
- **Status/capabilities changes**: Update `docs/STATUS.md`
