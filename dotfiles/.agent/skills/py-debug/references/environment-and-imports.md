# Environment and imports

Contents: [Which interpreter is running](#which-interpreter-is-running) · [Which file a module resolves to](#which-file-a-module-resolves-to) · [sys.path and env](#syspath-and-env) · [Installed-package truth](#installed-package-truth) · [Stale code and bytecode](#stale-code-and-bytecode) · [ModuleNotFoundError patterns](#modulenotfounderror-patterns) · [Circular imports and import-time hangs](#circular-imports-and-import-time-hangs)

## Which interpreter is running

```bash
uv run python -c 'import sys; print(sys.executable, sys.prefix)'
uv run python -VV
```

For "works in my shell, fails here" (or the reverse), run the same one-liner with bare `python` and compare — the one deliberate exception to the uv-only rule; two different `sys.executable` values explain the whole discrepancy.

## Which file a module resolves to

```bash
uv run python -c 'import mod; print(mod.__file__)'
```

- A project file shadowing a stdlib or installed module (a local `queue.py`, `email.py`, `test.py`, `types.py`) is the classic cause; the signature errors are "AttributeError: partially initialized module" and "module 'x' has no attribute 'y'" for attributes that clearly exist.
- Check for same-named files where the script lives, because `sys.path[0]` (the script's directory) wins over site-packages: `ls *.py` next to the entry point.
- Namespace packages have no `__file__`; `print(mod.__path__)` shows which directories merged into the package.

## sys.path and env

```bash
uv run python -c 'import sys, pprint; pprint.pp(sys.path)'
printenv PYTHONPATH PYTHONHOME PYTHONSTARTUP VIRTUAL_ENV UV_PROJECT_ENVIRONMENT
```

Look variables up by name; never dump or grep the whole environment, which can print secret values.

A leaked `PYTHONPATH` pointing at another checkout silently wins over the project's own packages; unset it and rerun before debugging further.

## Installed-package truth

- `uv pip list` shows what is actually in the environment; `uv pip show -f pkg` shows the exact installed files.
- Compare against the imported reality: `uv run python -c 'import pkg; print(pkg.__version__, pkg.__file__)'`.
- Every `uv run` command already locks and syncs before it runs; when drift is what you are diagnosing, use `uv run --no-sync` so the evidence is not repaired before you read it.
- **IF** the lockfile and environment have drifted **THEN** `uv sync` (state-changing: run it as a fix step, not as diagnosis) **ELSE** continue diagnosing elsewhere; `uv lock --check` tells you whether the lockfile itself is stale.

## Stale code and bytecode

Traceback line numbers that do not match the source, or a deleted module that still imports, usually mean the running code is not the file you are reading. Check in this order:

1. The process predates the edit: a long-running process keeps the modules it imported in `sys.modules`, while tracebacks read the current source from disk. Restart it.
2. A different copy is imported: print `mod.__file__` (above); a non-editable install in site-packages or a second checkout on `sys.path` wins over the file you edited.
3. Bytecode: Python 3 ignores `__pycache__/*.pyc` whose source is gone and revalidates the rest by source mtime and size, so stale bytecode is rare. The exceptions are a sourceless legacy `mod.pyc` beside where `mod.py` used to be (it still imports), and hash-based `.pyc` files built with unchecked hashes, which are never revalidated. Locate both kinds and delete what you find:

```bash
find . -name '*.pyc' -not -path '*/__pycache__/*' -not -path './.venv/*'
uv run python -c 'import pathlib; [print(p) for p in pathlib.Path(".").rglob("*.pyc") if ".venv" not in p.parts and int.from_bytes(p.read_bytes()[4:8], "little") == 1]'
```

The second command prints unchecked hash-based files: flag value 1 in the `.pyc` header (PEP 552).

## ModuleNotFoundError patterns

| Pattern | Cause |
|---|---|
| Works after `uv sync`, not before | dependency present in `pyproject.toml` but environment stale |
| Only an optional feature's import fails | missing extra: `uv sync --extra name` |
| The project's own package not importable | missing editable install or wrong `[tool.uv]` / build config |
| Import works from repo root, fails elsewhere | cwd-relative import; run as a module: `uv run python -m pkg.mod`, not `uv run python pkg/mod.py` |
| Two distributions provide one namespace | namespace-package confusion; check `mod.__path__` for the merged directories |

## Circular imports and import-time hangs

- "cannot import name 'x' from partially initialized module" is a circular import; the traceback shows the cycle, and moving one import into the function that needs it breaks it.
- When an import hangs or is inexplicably slow, see where time is going (each line is cumulative microseconds per module):

```bash
timeout 60 uv run python -X importtime -c 'import mod' 2>&1 | tail -30
```
