---
name: py-typecheck
description: Runs the project's configured Python type checker (ty, mypy, or pyright) and fixes diagnostics until it exits clean. Use when asked to type check, fix type errors, or fix type hints and annotations. Not for lint or style errors (py-lint-fix).
disable-model-invocation: true
---

# py-typecheck

Run the project's type checker and fix what it reports.

Trailing input after `/skill:py-typecheck` names target paths, rule codes, or `check-only`; with no paths, check the whole project.

## Checker

Use the checker the project is configured for, never a different one:

- ty: `[tool.ty]` in `pyproject.toml`, a `ty.toml`, or ty as a dev dependency → `uv run ty check`
- mypy: `[tool.mypy]`, `mypy.ini`, `.mypy.ini`, or a `[mypy]` section in `setup.cfg` → `uv run mypy`, plus `.` when no paths were requested and the config sets no `files`, `packages`, or `modules` (mypy exits 2 without a target)
- pyright: `[tool.pyright]` or `pyrightconfig.json` → `uv run pyright`

Confirm against what CI and `.pre-commit-config.yaml` run, since that is the gate the fixes must pass.

- **IF** no checker is configured **THEN** report that and stop; choosing or adding a checker is the user's decision.
- **IF** several are configured **THEN** run each one that CI or pre-commit runs; **IF** neither runs any of them **THEN** ask which checker is authoritative and run none until answered (a subagent returns the question to its parent).
- **IF** the configured checker is not installed in the project environment **THEN** report it; do not install it or substitute another checker.

When the checker is ty, read `references/ty.md` before the first run: it holds ty's exit codes, flags, autofix, rule notes, and suppression syntax. The workflow and fix policy below apply to every checker; with mypy or pyright, use that checker's own flags and rule codes.

## Scope and mode

- Resolve the scope once into `<paths>`: the requested paths, or the checker's configured project scope when none were given. Pass the same `<paths>` to every run.
- **IF** the request is to check or report **THEN** run the checker once, report diagnostics grouped by rule with `file:line`, and edit nothing **ELSE** run the fix workflow.

## Fix workflow

1. Run the checker from the repo root so config and `.venv` resolution work. Exit 0 means clean and exit 1 means diagnostics to fix. Any other exit code is a config, usage, or internal error: surface it to the user and don't work around it (mypy: 2; pyright: 3 = config error, 4 = bad arguments or paths; ty: `references/ty.md`).
2. Triage: group diagnostics by rule.
3. Fix environment problems first: unresolved imports or attributes on installed packages usually mean a missing dependency, missing stubs, or the wrong interpreter. Unresolved modules produce `Unknown`/`Any` types that cascade into downstream noise, so re-run after fixing them before judging anything else.
4. ty only: apply autofixes as `references/ty.md` describes, then review the diff.
5. Fix the rest manually, definition sites before call sites: one corrected signature or attribute type clears many call-site diagnostics.
6. Re-run after each group of fixes until the checker exits clean.
7. When an edit changes runtime behavior, run the tests that cover the changed code and report any failures honestly.

## Fix policy

Establish the runtime contract first: which values actually reach this code, from its callers, tests, and stubs. Then prefer, in order:

1. Fix the annotation when it is wrong about what the code does at runtime.
2. Fix the code when it is wrong about its contract — the diagnostic is often a real bug. A behavior change needs a reproducer (a failing test or command) that passes after the fix.
3. Narrow where the contract guarantees the narrower type: `isinstance`, `is None` checks, `match`; `TypeIs`/`TypeGuard` for reusable predicates.
4. `cast()` only at genuine knowledge boundaries (deserialization, framework magic), with a comment saying why it is safe.
5. Targeted rule-specific ignore with a stated reason — last resort.

Never add a fallback branch, default value, or early return only to silence a diagnostic; that changes behavior without a reason. Never loosen a type to `Any` to silence a diagnostic. Never use a bare ignore. Never edit checker config to silence a rule unless asked. Leave excluded, vendored, and generated code alone.

When a diagnostic contradicts runtime reality, verify (run the code path, read the stub) before concluding it is a false positive. Suppress it with a rule-specific ignore plus a comment naming the suspected checker bug — never contort correct code to please the checker.

## Suppression syntax

Rule-specific ignores only: mypy `# type: ignore[<code>]`, pyright `# pyright: ignore[<rule>]`, ty per `references/ty.md`.

## References

- `references/ty.md` — read before the first run when the project uses ty: exit codes, flags, autofix, rule notes, suppression syntax.
- `references/configuration.md` — read when a ty project needs configuring (`[tool.ty.*]` / `ty.toml`), an explicitly requested gradual adoption, CI output formats, or silencing rules for untyped third-party paths.
