In this repo refrain from using engrammar mcp, we are developing engrammar here and we want to determine how to automatically improve learning rather than just fixing the db state.

## Tracking Work

Don't let ideas stay only in conversation — if it's worth discussing, it's worth writing down.

### What goes where

| Type | Location | Naming | Index |
|------|----------|--------|-------|
| Bugs, design flaws | `issues/open/` | `[severity]-NNN-slug/issue.md` | `issues/ISSUES.md` |
| Features, planned work | `tasks/open/` | `[priority]-NNN-slug/task.md` | `tasks/tasks.md` |
| Completed tasks | `tasks/completed/` | `[priority]-NNN-slug/task.md` | `tasks/tasks.md` |
| Loose ideas | `tasks/ideas/` | `descriptive-name.md` | listed in `tasks/tasks.md` |

- **Issues** use severity: `[1]` Critical, `[2]` High, `[3]` Medium, `[4]` Low
- **Tasks** use priority: `[1]` High, `[2]` Medium, `[3]` Low
- Both use complexity: `C1` low-hanging, `C2` medium, `C3` high

### When to capture

- Discussing a new feature or improvement? Create a task.
- Found a bug or design flaw? Create an issue.
- Have a vague idea that needs more thought? Add it to `tasks/ideas/`.
- If something is both a bug and needs feature work, create an issue for the problem and reference it from the task.

### Workflow

1. During conversation, identify things worth tracking.
2. Create the folder + markdown file in the right location.
3. Update the corresponding index file (`ISSUES.md` or `tasks.md`).
4. When starting work on a task/issue, note it in the file.
5. When done, move issues to `issues/resolved/` and move tasks to `tasks/completed/`, then check off/update status in the index.
