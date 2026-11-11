---
name: py-test-gen
description: Writes behavior-first pytest tests for Python code and proves each one by running it with uv and breaking the code it covers; also writes failing bug reproductions and fills coverage gaps. Use whenever a feature, fix, or refactor writes or changes Python code (except one-off or throwaway scripts, or when the user says not to write tests), and when asked to write tests, add coverage, reproduce a bug as a failing test, or find what's untested.
---

# py-test-gen

Generate behavior-first pytest tests and prove they work: every generated test is executed with `uv run pytest` and shown to fail when the code it covers is broken before the task is reported done.

## Arguments

Trailing input after `/skill:py-test-gen` selects the target and mode:

- A path, function name, or class name → default mode on that target.
- `coverage`, `gaps`, or a percentage → coverage-gap mode, scoped to any path also given.

Conversational requests map the same way: "test this function" → default mode; "raise coverage" → coverage-gap mode; "what's untested" → coverage-gap mode steps 1–2 only, reporting the classified gaps without writing tests.
With no input, run automatic mode on the Python code the current task wrote or changed; when the conversation does not show which code that is, take it from `git diff` and `git status`, and if still ambiguous, ask one question — don't guess.

## Automatic mode

This mode runs without being asked whenever you write or change Python code, so the change ships with its tests.

1. **IF** the code is a one-off or throwaway script (run once and discarded, not imported and not kept as a project tool) **OR** the user said not to write tests **THEN** write no tests, say in your report that tests were skipped and why, and stop.
2. List the behaviors the task added or changed: new functions and branches, changed outputs or error paths, the bug a fix removes. Untouched code is out of scope.
3. **IF** the list is empty (a pure refactor, rename, or formatting change) **THEN** add no tests: run the existing tests that cover the changed code and report the result **ELSE** run default mode on that list.
4. Update an existing test only when it asserts behavior the task changed on purpose; a bug fix gets a test that fails before the fix and passes after it (red-before-green in `## Detection check`).

## Environment rules

- Run every Python command through uv: `uv run pytest`, `uv run ruff`. Never bare `python`/`pip`, never another runner.
- Verify dependencies before starting: `uv run pytest --version`; for coverage-gap mode also `uv run python -c "import pytest_cov"`. If missing, ask the user before running `uv add --dev pytest pytest-cov`.
- `[--no-cov]` in the commands below means: include `--no-cov` when pytest-cov is installed, so `addopts` coverage and any `fail_under` threshold do not fail a run over a few tests, and omit it otherwise, since pytest rejects the flag without the plugin. Only the coverage-gap command measures coverage.
- Discover project conventions before writing anything: test layout (`tests/` mirror vs `test_*.py` alongside the source), shared fixtures in `conftest.py`, `[tool.pytest.ini_options]` in `pyproject.toml`, existing naming style. New tests must look native to the repo.

## Workflow (default mode)

1. Read the code under test in full, plus its immediate callees, any existing tests for the module, and every `conftest.py` on the path to it.
2. Map behaviors before writing: list the observable behaviors, input classes, edge cases, and error paths as a short checklist. This list drives the tests — not the implementation's branch structure.
3. Write tests per `## Test rules`, placed per the project layout.
4. Run `uv run pytest [--no-cov] <new-file> -x -q`.
5. On failure, decide whether the test or the code under test is wrong. **IF** the code is wrong **THEN** stop: leave the test failing (no `skip` or `xfail` without the user's agreement), and report expected versus actual behavior, the failing output, and the decision needed; fix the code only when that fix is part of the task. Never bend a test to make it pass.
6. Run `## Validation loop`; repeat steps 4–6 until everything passes or step 5 stops the task.

## Workflow (coverage-gap mode)

1. Resolve the target to a coverage source (a package, module path, or directory, never a function name or node id) and the tests that exercise it, then run: `uv run pytest <test-paths> --cov=<source> --cov-branch --cov-report=term-missing -q`.
2. Read the Missing column; open each uncovered region and classify it: untested branch, untested error path, trivia (`__repr__`, `if __name__ == "__main__"` guards), or apparently unreachable. Call code dead only after searching for callers and checking entry points (`[project.scripts]`, plugins), registrations (decorators, dispatch tables, `getattr`), and the public API; otherwise report it as apparently unreachable. Never test it.
3. Prioritize public API and error handling; for each gap, run default-mode steps 1–6 scoped to that behavior.
4. Re-run the coverage command; confirm the targeted lines and branches are now covered.
5. Coverage is a floor, not a target. Never add assertion-free or tautological tests to move the number. Report any gaps deliberately left open and why.

## Test rules

Every test must name the plausible bug it would catch and contain the observable check that catches it; the rules below are defaults in service of that.

### What to test

- Test behavior, not implementation: assert on return values and observable effects, never on private attributes or the call sequence of internals.
- One behavior per test. The name alone should say why the test could fail.
- Assert concrete values: `assert result == [3, 1]`, not `assert result` or an `isinstance` check, unless the type is the contract.
- No tautological tests: no asserting a mock returns what it was configured to return, no `assert x == x`.
- Error paths are first-class: `pytest.raises(ExcType)` around the narrowest call; add `match=` when the message distinguishes this failure from others the call can raise.
- "Never raises on any valid input" is a legitimate property-based test; an example-based test needs an assertion or `pytest.raises`.

### Structure

- Arrange-Act-Assert, separated by blank lines; one Act per test, unless the behavior is a sequence (replayed events, a state machine).
- Name tests `test_<unit>_<scenario>_<expected>` (e.g. `test_parse_line_item_empty_sku_raises_value_error`).
- Use `@pytest.mark.parametrize` instead of copy-pasted near-identical tests; add `ids=` when the parameters aren't self-describing. Don't parametrize unrelated behaviors together.
- Fixtures only for setup shared by 2+ tests or needing teardown — not for one-test setup, and never where they hide the Arrange step. Prefer a plain builder function when a fixture would add indirection without teardown.
- No branches in tests and no re-implemented production logic: a branch means you wanted two tests, a loop over cases means you wanted `parametrize`. A loop that replays a sequence of events, or checks each item of a result, is fine.

### Inputs

Treat this edge-case list as a menu, chosen where the contract makes each case matter: empty, `None`, boundaries (0, 1, max, off-by-one), duplicates, unicode/whitespace, very large inputs, negative numbers, wrong-but-plausible types.
Choose inputs that tell plausible wrong implementations apart: unequal nonzero operands, asymmetric values, numbers where rounding modes disagree.

### Determinism and isolation

- Deterministic always: freeze or inject time, inject or seed every RNG, no sleep-based waits, no network, `tmp_path` instead of real paths, `monkeypatch.setenv`/`delenv` for environment variables.
- Order-independent: no shared mutable state between tests; each test must pass when run alone by node-id (`uv run pytest [--no-cov] path/to/test.py::test_name`).

### Mocking (headlines — details in references/mocking-and-isolation.md)

- Mock at system boundaries only: network, database, clock, subprocess. Prefer a small fake over `MagicMock`. Don't mock what you own; never mock internals of the module under test.
- Mock-call assertions (`assert_called_once_with`) supplement value assertions. They stand alone only when the outgoing interaction is the behavior (the request sent, its payload, that nothing was sent); that still says nothing about how the far side handles it.

## Validation loop

1. Run `uv run pytest [--no-cov] <new-file> -q`. All tests pass; warnings acceptable only if pre-existing.
2. Detection check: show the tests catch the mistakes that matter by breaking the production code, never the test. See `## Detection check`.
3. Run the new tests together with the module's existing tests to catch ordering or isolation breakage, then run one new test alone by node-id.
4. If ruff is in the project: `uv run ruff format <file>` then `uv run ruff check <file>`. Otherwise match the surrounding style by hand — never introduce a formatter the project doesn't use.
5. Coverage-gap mode only: re-run the coverage command and confirm the targeted lines now show covered.
6. Report: test names added, behaviors covered, the detection evidence for each (mutant caught or red-before-green), any bugs found (with the failing output), and any gaps or surviving mutants left with the reason.

## Detection check

1. Pick the 1–3 most consequential mistakes the tests should catch (a flipped sign, an off-by-one boundary, a dropped dedupe, a missing `await`, an omitted write) and the one-line mutation of the production code that represents each.
2. Red-before-green: when the tests cover an existing file changed in this session (`git cat-file -e HEAD:<file>` succeeds), the pre-change version is itself the mutation — in the command below, replace the `sed` line with `git show HEAD:"$f" > "$f"` and the one-line check with `! cmp -s "$b" "$f" || exit 2`. A file created in this session has no pre-change version; use ordinary one-line mutations. Never use `git stash` or `git checkout`, which also move other uncommitted work.
3. Run each mutation as one shell command, so the file is always restored from a backup, on normal exit and on interrupt. Address the `sed` to the one line you mean (`42s/…/…/`), so a pattern that also appears elsewhere is not mutated too; the `diff` check stops the run unless exactly one line changed:

   ```bash
   f=src/billing/totals.py; b=$(mktemp) && cp -p "$f" "$b" && echo "backup=$b" && (
     trap 'cp -p "$b" "$f" && cmp -s "$b" "$f" && rm -f "$b" && echo restored' EXIT
     trap 'exit 130' INT TERM
     sed -i '42s/ROUND_CEILING/ROUND_HALF_EVEN/' "$f"
     [ "$(diff "$b" "$f" | grep -c '^>')" -eq 1 ] || { echo "expected exactly one changed line"; exit 2; }
     timeout 120 uv run pytest [--no-cov] -q <node-ids>; echo "exit=$?"
   )
   ```

4. Only a failure at the intended assertion counts as caught; an import, collection, or fixture error, or a timeout, is inconclusive. Without `restored` in the output, copy the backup back before doing anything else. Re-run the tests green afterwards.
5. Classify every surviving mutant: test gap (strengthen or add a test), equivalent (show why), or outside the contract; report the rest as gaps.
6. Never mutate a file someone else is editing (check `git status` and the conversation). Skip the check for trivial or purely declarative changes and say so.

## When the code resists testing

If code can't be tested without refactoring — hard-coded I/O, module-level side effects, global state — propose the minimal seam to the user (usually parameter injection) instead of deep-mocking around it. A test that needs three nested patches is a design report, not a test.

## Escape hatch

If the user explicitly asks for something different — unittest style, doctests, no fixtures, a specific layout, tests for private helpers — their instruction wins over these defaults. The validation loop (write → run → detection check) still applies; it is the non-negotiable part.

## References

- `references/example.md` — read before writing the first test in a repo with no existing tests to imitate: a complete test module in the expected shape.
- `references/domain-checks.md` — read when the code has exact numeric contracts (money, measurements, rounding), stateful objects or event sequences, retries or cancellation, pandas or numpy data, or a fake standing in for an external system.
- `references/property-based.md` — read when the user asks for property-based or Hypothesis tests, or when the target is a pure function over structured input (parsers, encoders, codecs, math) where properties beat examples.
- `references/mocking-and-isolation.md` — read when the code under test touches network, database, filesystem beyond `tmp_path`, subprocess, time, randomness, environment variables, or async code.
