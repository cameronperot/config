# ty configuration

Full reference: https://docs.astral.sh/ty/reference/configuration/

## Where config lives

- `[tool.ty.*]` tables in `pyproject.toml`, or a standalone `ty.toml` (same tables without the `tool.ty` prefix).
- `--config-file <path>` points at a `ty.toml` explicitly (a `pyproject.toml` is not allowed there). `-c "<key> = <value>"` overrides a single option and beats all config files.

## Rules

```toml
[tool.ty.rules]
possibly-unresolved-reference = "warn"  # error | warn | ignore
division-by-zero = "error"
all = "warn"                            # set a default for every rule
```

CLI equivalents: `--error <rule>` / `--warn <rule>` / `--ignore <rule>` (repeatable; `all` works there too).

## Environment

```toml
[tool.ty.environment]
python = "./.venv"         # interpreter or venv used to resolve third-party imports
python-version = "3.13"    # defaults to the minimum of project.requires-python
root = ["./src"]           # first-party module roots
extra-paths = ["./stubs"]  # additional module search paths
```

Under uv these usually need nothing; set `python` only when the environment to check is not the project `.venv`.

## File selection

```toml
[tool.ty.src]
include = ["src", "tests"]
exclude = ["generated", "**/migrations"]
respect-ignore-files = true  # honors .gitignore (default)
```

## Terminal

```toml
[tool.ty.terminal]
output-format = "concise"  # full (default) | concise | github | gitlab | junit
error-on-warning = false   # unset: warnings exit 1 (ty 0.0.89); false: only errors fail the run
```

## Per-path overrides

The right tool for untyped third-party or generated code — instead of scattering ignore comments:

```toml
[[tool.ty.overrides]]
include = ["src/vendored/**"]

[tool.ty.overrides.rules]
unresolved-attribute = "ignore"
possibly-missing-attribute = "ignore"
```

## Gradual adoption

Only when the user has asked to adopt ty or relax its gate; ordinary fixing keeps the existing gate.

1. Run `uv run ty check --output-format concise` and tally diagnostics per rule.
2. Demote the noisiest error-level rules to `warn` in `[tool.ty.rules]`; leave every other rule at its default level (some rules already default to `warn`, others to `ignore`).
3. Set `error-on-warning = false` in `[tool.ty.terminal]`: warnings exit 1 by default, so without it the demoted rules still fail CI. The warnings stay visible in the output.
4. Fix all errors; land CI at that bar.
5. Ratchet: promote one demoted rule back to `error`, fix its diagnostics, repeat until the table is empty.
6. Fix the remaining warnings, including those from rules that warn by default, then remove `error-on-warning = false`; until they are fixed, removing it fails CI.

## CI

- Exit codes: 0 = clean · 1 = diagnostics at warning level or above · 2 = config/usage/IO error · 101 = internal error.
- `--output-format github` (workflow annotations), `gitlab` (Code Quality JSON), `junit` (XML).
- `--exit-zero-on-warning` fails only on errors; `--error-on-warning` fails on warnings (cannot combine with the exit-zero flags); `--exit-zero` never fails (reporting-only jobs).
