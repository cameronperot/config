---
name: py-project-init
description: Initializes a new Python project on the uv/ruff/ty/pytest stack — src/ layout, pyproject.toml, pre-commit, CI, git init — then validates end to end. Use when explicitly asked to create, scaffold, or bootstrap a new Python project, package, library, CLI, or app.
disable-model-invocation: true
---

# py-project-init

Scaffold a new Python project on the uv/ruff/ty/pytest stack and prove it works: the task is not done until the full validation loop passes clean in one uninterrupted run.

## Arguments

Trailing input after `/skill:py-project-init` sets the project parameters; tokens are order-independent:

- `lib` / `library` / `package` → library; `cli` / `tool` / `command` → CLI; `app` / `application` / `service` → app.
- A bare `snake_case`/`kebab-case` identifier → project name.
- A path (contains `/` or is `.`) → target directory.
- A version like `3.13` → Python version floor.
- A license identifier (`mit`, `apache-2.0`, `proprietary`) → license.
- `no-ci` / `no-precommit` / `no-git` → disable that feature.
- Remaining free text → project description (feeds `[project]` description and the README).

Conversational requests map the same way ("bootstrap a CLI called reconcile" → CLI named `reconcile`).
With no input, resolve every parameter from the Decisions table below.

## Decisions: ask vs. infer

Ask at most one consolidated question, and only when the project type is not inferable. That message must also state every assumed default below, so the user can veto any of them in the same reply.

| Decision | Policy |
|---|---|
| Project type | Infer ("importable", "pip install" → library; "command", "run it" → CLI). **IF** not inferable **THEN** ask **ELSE** proceed. |
| Project name | From args, else the target directory name. Confirm (inside the same question) only when the directory name is generic (`src`, `tmp`, `projects`, home). |
| Target directory | cwd unless a path is given. Never ask. |
| Python version | `uv python list` → newest stable CPython (skip rc/dev/freethreaded builds). Never ask, never hardcode. |
| License | Proprietary by default: `license = "LicenseRef-Proprietary"` in `[project]`, no LICENSE file. Any user-stated license wins. Report the choice in the summary. |
| Git repo state | Detect with `git rev-parse --is-inside-work-tree` (skipped under `no-git`). Never ask; drives the existing-repo escape hatch. |
| CI | On when the project is the repo root and git is in use; otherwise auto-skip with a note. |
| pre-commit | On unless `no-precommit` or `no-git` (pre-commit needs a git repository). |

## Environment rules

- Every command through uv: `uv init`, `uv add --dev`, `uv run <tool>`. Never bare `python`/`pip`/`pipx`.
- Preflight `uv --version`, and `git --version` unless `no-git`. **IF** uv is missing **THEN** stop and give the user the official installer command (`curl -LsSf https://astral.sh/uv/install.sh | sh`) — do not improvise another install path. The skill has no other dependencies.
- Never overwrite or delete existing files.

## Workflow

1. Resolve every decision in the table above; ask the single consolidated question only if needed.
2. Preflight: verify uv, and git unless `no-git`; inspect the target directory. **IF** it is non-empty **THEN** use the escape hatch **ELSE** continue. Unless `no-git`, record whether it is already inside a git repo.
3. Scaffold: library → `uv init --lib <dir>`; CLI or app → `uv init --app --package <dir>` (src/ layout plus a `[project.scripts]` entry point). Always pass `--name <name>`, `--python <chosen>`, and `--description "<description>"`; add `--vcs none` under `no-git`, and `--no-workspace` unless the user wants the project to join an enclosing uv workspace (without it, uv adds the project to that workspace's members). Run every later command from `<dir>`: start each shell call with `cd <dir> &&`, since the working directory may not persist between calls. Then verify what uv actually generated (src/ layout, `.python-version`, `.gitignore`, README, `py.typed` for libraries, git init, build backend) instead of assuming — uv's defaults change between versions.
4. Complete `[project]` in pyproject.toml: description, authors (uv fills them from git config — verify; under `no-git` or without a git identity, leave them out unless the user gave them), `requires-python` floor, license marker per the table. Then merge in the `[tool.*]` blocks from `references/pyproject-snippets.md`.
5. Add dev dependencies: `uv add --dev ruff ty pytest pytest-cov pre-commit` — unpinned; `uv.lock` does the per-project pinning.
6. Project files: flesh out README.md — title, one-line purpose, install (`uv sync`), usage, development commands (test/lint/typecheck). Merge `assets/gitignore` into the generated `.gitignore` (union, no duplicates). Libraries keep `src/<pkg>/py.typed`; apps and CLIs don't need it. Add a one-line Google-style docstring to the generated `src/<pkg>/__init__.py` (module) and to the function uv generated in it (`hello` or `main`); the snippet's D rules fail `ruff check` without them (D104, D103).
7. pre-commit (unless disabled): copy `assets/pre-commit-config.yaml` to the repo root as `.pre-commit-config.yaml`, run `uv run pre-commit autoupdate` (best effort — the shipped revs are the offline fallback), then `uv run pre-commit install`.
8. CI (unless disabled or not at repo root): copy `assets/github-ci.yml` to `.github/workflows/ci.yml`.
9. Write one smoke test, `tests/test_smoke.py`: import the package and assert on `__version__` or a trivial call, so pytest has something to collect (an empty suite exits 5). Do not write real tests here — that is py-test-gen's job; recommend it in the report.
10. Run the validation loop below until it passes clean in a single pass.
11. Never stage or commit. Leave the files for the user to review and commit (the git-commit skill), and say so in the report.
12. Report: files created; inferred decisions (type, name, Python version, license); every validation step that could not run, which makes the task incomplete rather than done; the everyday commands (`uv run pytest`, `uv run ruff check .`, `uv run ty check`, `uv add <dep>`); next steps (py-test-gen for real tests, py-lint-fix if lint drifts).

## Validation loop

1. `uv sync`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run ty check`
5. `uv run pytest -q`
6. Package check: library → `uv build`; CLI or app → `uv run <script-name>` (the `[project.scripts]` entry) exits 0.
7. `uv run pre-commit run --files <files>`, listing every file this skill created. `--files` checks untracked files without touching the git index; never stage to make pre-commit see them. Hooks that modify files fail their first run; re-run. Skip this step if pre-commit is disabled.

Any failure: fix the root cause — never weaken a config, add an ignore, or delete a check to get past it — then restart from step 2 (step 1 only if dependencies changed). Done means steps 2–7 pass in one uninterrupted run. A step that could not run is reported as not run, never as passed.

## Escape hatches

- Explicit user instruction beats any default: a different license (write that license's text as LICENSE and set the matching SPDX expression), no CI, flat layout, a pinned Python version. The validation loop still applies to whatever is set up.
- User wants a different stack (poetry, mypy, flake8, …): the bundled templates and snippets no longer apply — say so and set up their stack manually; don't graft these configs onto it.
- Non-empty target directory: list the conflicting files and offer exactly two paths — initialize around them (`uv init` in place, merge configs by hand) or stop. Never overwrite.
- Existing git repo / monorepo subproject: skip git init (`--vcs none`). CI and pre-commit only work at the repo root — add the workflow there only if the user wants it, and merge hooks into an existing root `.pre-commit-config.yaml` rather than adding a second one. Put gitignore entries wherever the repo already keeps them.
- No network: a failed `pre-commit autoupdate` is harmless — keep the shipped revs and note it. A failed hook-environment fetch means validation step 7 cannot run: report the task as incomplete, with the command to rerun once online.

## Files

- `references/pyproject-snippets.md` — read at workflow step 4: canonical `[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]` blocks and the ty zero-config policy.
- `assets/pre-commit-config.yaml` — copy at step 7, then autoupdate.
- `assets/github-ci.yml` — copy at step 8. Actions are pinned to major tags; if CI reports a deprecated action, bump the major.
- `assets/gitignore` — merge at step 6.
