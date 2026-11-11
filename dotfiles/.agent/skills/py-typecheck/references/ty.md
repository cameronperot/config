# ty

ty-specific commands, rule notes, and suppression syntax for the py-typecheck workflow. Project configuration (`[tool.ty.*]`, `ty.toml`) is in `configuration.md`.

## Running ty

- Command: `uv run ty check <paths>`; add `--output-format concise` when the diagnostic count is large.
- Exit codes: 0 = clean, 1 = diagnostics at warning level or above (unless the project sets `error-on-warning = false`), 2 = config/usage/IO error (surface it to the user, don't work around it), 101 = internal ty error (checker bug — report it, don't chase it).
- Unfamiliar rule: `uv run ty explain rule <rule>`.
- Wrong interpreter: point ty at the right one with `--python <path>`.
- Autofix (fix workflow step 4): `uv run ty check --fix <paths>` (e.g., removes stale ignore comments), then review the diff — the tool is pre-1.0.
- Never run `--add-ignore`: it blanket-suppresses every diagnostic.

## Rule notes

Default levels below were checked with `ty explain rule` on ty 0.0.89; re-check with `uv run ty explain rule <rule>` when the project pins another version.

- `possibly-unresolved-reference`, `possibly-missing-attribute`, `division-by-zero`: ignored by default, so if one fires the project enabled it. Check whether the flagged path can actually occur before changing code; when it can, restructure control flow (initialize before the branch, or raise in the else arm) rather than suppressing.
- `possibly-missing-implicit-call`, `possibly-missing-submodule`: warn by default.
- `no-matching-overload`: usually a wrong argument type upstream; read the actual overloads before touching the call site.
- `unused-ignore-comment` (warn by default): delete the stale ignore (`--fix` does this). Trap: this rule can only be suppressed by its own code, not by a bare `# ty: ignore` or `# type: ignore`.

## Suppression syntax

```python
x = f(arg)  # ty: ignore[invalid-argument-type]
y = g()  # ty: ignore[missing-argument, invalid-argument-type]
z: int = h()  # type: ignore[ty:invalid-assignment]  (scopes to ty in multi-checker repos)
```

- Place on the first or last line of a multi-line violation.
- File-level: the same comment on its own line before any code in the file.
- PEP 484 `# type: ignore` is honored but suppresses everything on the line — always use rule codes.
- `@no_type_check` suppresses a whole function (functions only); avoid it for the same reason.
