---
name: skill-taskwarrior
description: Manages personal tasks with the Taskwarrior CLI (task), pairing each task with description.md and definition-of-done.md files under ~/.my-tasks/. Use when the user asks to create a task (e.g. "create a task for X in project Y"), read or update a task's description or definition of done (e.g. "what's the status of my current task", "update the definition of done for that task"), start or stop time tracking ("start task", "stop task"), or mark a task complete ("mark task done"). Do NOT use for generic to-do apps, calendars, or non-Taskwarrior project management.
license: CC-BY-4.0
metadata:
  author: mesbrj
  version: 1.0.0
---

# Taskwarrior Task Workflow

Creates and manages Taskwarrior tasks that carry a `description.md` and `definition-of-done.md` alongside them, and drives each task through its start/stop/done lifecycle.

## Core convention

Every task gets two markdown files stored at `$HOME/.my-tasks/<task-uuid>/`:

- `description.md` — the detailed task description
- `definition-of-done.md` — the definition of done

These are linked to the task via `task annotate`, in that exact order, and are never re-annotated afterward. Retrieval depends on `description.md` always being annotation #1 and `definition-of-done.md` always being annotation #2 — never add any other annotation to a task managed by this workflow, or the indices will shift and lookups will break.

## Instructions

### Step 1: Create the task

```bash
task add "<task-name>" project:"<project-name>"
```

### Step 2: Resolve its UUID

```bash
task description:"<task-name>" _uuids
```

If this returns more than one UUID (another task already has the same description), show the user each match's project and UUID (`task <uuid> info`) and ask which one they meant. Never guess — do not proceed until the task is unambiguous.

### Step 3: Create the description and definition-of-done files

```bash
mkdir -p "$HOME/.my-tasks/<task-uuid>"
touch "$HOME/.my-tasks/<task-uuid>/description.md"
touch "$HOME/.my-tasks/<task-uuid>/definition-of-done.md"
```

Write the actual task description and definition of done into these files — this is content you (the agent) author based on the conversation, not boilerplate.

### Step 4: Link the files to the task

Order matters — annotate `description.md` first, `definition-of-done.md` second:

```bash
task <task-uuid> annotate "$HOME/.my-tasks/<task-uuid>/description.md"
task <task-uuid> annotate "$HOME/.my-tasks/<task-uuid>/definition-of-done.md"
```

### Step 5: Read a task's description / definition of done

```bash
task _get <task-uuid>.annotations.1.description   # path to description.md
task _get <task-uuid>.annotations.2.description   # path to definition-of-done.md
```

Open the returned paths to read their content.

### Step 6: Update a task's description / definition of done

Locate the paths the same way as Step 5, then edit that file's content directly. The annotation only stores a file path pointer — it does not need to change when the content changes, so do not re-run `task annotate` for an update; doing so would add a duplicate annotation and shift the indices used everywhere else.

### Step 7: Start / stop time tracking

```bash
task <task-uuid> start
task <task-uuid> stop
```

### Step 8: Mark the task done

```bash
task <task-uuid> done
```

## Example

User: "Create a task to implement user authentication in the Website Redesign project."

```bash
task add "Implement user authentication" project:"Website Redesign"
task description:"Implement user authentication" _uuids
# -> acbdb0d6-709e-478d-bca0-8f5dc5e4e073
mkdir -p "$HOME/.my-tasks/acbdb0d6-709e-478d-bca0-8f5dc5e4e073"
touch "$HOME/.my-tasks/acbdb0d6-709e-478d-bca0-8f5dc5e4e073/description.md"
touch "$HOME/.my-tasks/acbdb0d6-709e-478d-bca0-8f5dc5e4e073/definition-of-done.md"
# ...write content into both files...
task acbdb0d6-709e-478d-bca0-8f5dc5e4e073 annotate "$HOME/.my-tasks/acbdb0d6-709e-478d-bca0-8f5dc5e4e073/description.md"
task acbdb0d6-709e-478d-bca0-8f5dc5e4e073 annotate "$HOME/.my-tasks/acbdb0d6-709e-478d-bca0-8f5dc5e4e073/definition-of-done.md"
```

Result: the task exists with both files linked as annotations #1 and #2.

User: "What's the status of that task?"

```bash
task _get acbdb0d6-709e-478d-bca0-8f5dc5e4e073.annotations.1.description
task _get acbdb0d6-709e-478d-bca0-8f5dc5e4e073.annotations.2.description
# open both paths and summarize their content
```

User: "Start working on it." → "I'm done for now." → "Mark it done."

```bash
task acbdb0d6-709e-478d-bca0-8f5dc5e4e073 start
task acbdb0d6-709e-478d-bca0-8f5dc5e4e073 stop
task acbdb0d6-709e-478d-bca0-8f5dc5e4e073 done
```

## Troubleshooting

### Error: `task description:"<name>" _uuids` returns multiple UUIDs

Cause: More than one task shares that exact description.
Solution: Show the user each match's project and UUID (`task <uuid> info`) and ask them to pick one. Do not guess.

### Error: `task _get <uuid>.annotations.1.description` (or `.2.`) returns empty or an unexpected value

Cause: The task doesn't have both annotations in the expected order — Step 4 was skipped, done out of order, or a third-party annotation was added to this task after setup, shifting the indices.
Solution: Run `task <uuid> info` to see all annotations in order and find which index actually holds `description.md` / `definition-of-done.md`. If a file is missing, redo Steps 3-4 for that file only, and don't disturb the existing annotation order.

## Out of scope (v1)

This skill only covers create / describe / update / start / stop / done. It does not handle listing or querying tasks, changing project/priority/due date, or deleting tasks — use plain `task` commands for those, or check with the user before improvising new behavior here.
