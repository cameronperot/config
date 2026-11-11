---
name: py-lint-fix
description: Fixes Python lint errors with ruff and formats with ruff format until ruff check passes. Use when asked to lint Python code, fix ruff errors, or pass CI lint checks. Not for type errors (py-typecheck).
disable-model-invocation: true
---

# py-lint-fix

Fix Python lint errors with ruff, then format. Run ruff through the project's environment: `uv run ruff` by default; if the project does not use uv, invoke `ruff` via the project's own environment instead, and use that runner for every command below.

Trailing input after `/skill:py-lint-fix` names target paths, rule codes, or `check-only`; with no paths, the scope is the whole project.

## Scope and mode

- Resolve the scope once into `<paths>`: the requested paths, or `.` for the whole project. Pass the same `<paths>` to every command below, so a scoped request never touches other files.
- Rule codes narrow what you triage and report, not what is checked: filter the output of the full `ruff check <paths>` run. Never pass `--select` or `--ignore` to change what is checked.
- **IF** the request is to check, report, or "is this clean?" **THEN** run check-only mode and make no edits **ELSE** run the fix workflow.

## Check-only mode

1. `uv run ruff check <paths>` from the repo root.
2. `uv run ruff format --check --diff <paths>`.
3. Report the violations by rule and file, the files that would be reformatted, and both exit codes. Edit nothing.

## Fix workflow

1. Survey the damage: run `uv run ruff check <paths>` from the repo root so config resolution works. Respect the project's config (`pyproject.toml` / `ruff.toml` / `.ruff.toml`). When the violation count is large, run `uv run ruff check --statistics <paths>` to plan the work rule by rule.
2. Apply safe auto-fixes: `uv run ruff check --fix --no-unsafe-fixes <paths>`. `--no-unsafe-fixes` keeps a project-level `unsafe-fixes = true` from slipping unsafe fixes into this pass. Review the resulting diff anyway: a fix being safe does not make it in scope.
3. Handle unsafe fixes: preview with `uv run ruff check --unsafe-fixes --diff <paths>` and review every hunk for semantic changes — e.g. RUF015 rewrites `list(x)[0]` to `next(iter(x))`, which raises `StopIteration` instead of `IndexError` on an empty input. **IF** all hunks are semantically safe **THEN** apply with `uv run ruff check --fix --unsafe-fixes <paths>` **ELSE** fix those spots manually and leave the unsafe fixer alone.
4. Manually fix whatever remains. Fix the root cause of each violation; do not silence it.
5. Re-run `uv run ruff check <paths>` and repeat steps 2–4 until it exits 0. Exit 1 means violations remain; exit 2 means a config or usage error or an internal ruff error — surface that to the user, don't work around it.
6. Format: preview with `uv run ruff format --diff <paths>`. **IF** a file's diff reaches lines outside the code this task changed **THEN** format only the files whose diff is confined to the task's changes and report the others as format drift **ELSE** run `uv run ruff format <paths>`. A whole-project request formats the whole project.
7. Gate: run `uv run ruff check <paths>` and `uv run ruff format --check <paths>`. **IF** either fails **THEN** return to step 4 **ELSE** done.
8. Verify behavior: when a fix could change runtime behavior (any unsafe fix or manual rewrite), run the tests that cover the changed files. Report failures honestly rather than papering over them.

## Fix policy

- Never add a bare `# noqa`. Use rule-specific `# noqa: <CODE>` only for genuine false positives, and state the justification when you add one.
- Never edit lint configuration to silence rules unless the user explicitly asks.
- Leave excluded, vendored, and generated code alone.
- Some E501 violations survive `ruff format` (long string literals, comments, URLs) — fix those manually by restructuring the line.
