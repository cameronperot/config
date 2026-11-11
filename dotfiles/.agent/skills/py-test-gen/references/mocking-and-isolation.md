# Mocking and isolation recipes

Supplements the mocking headlines in SKILL.md. Read when the code under test touches network, database, filesystem beyond `tmp_path`, subprocess, time, randomness, environment variables, or async code.

## Contents

- [Decision ladder](#decision-ladder)
- [monkeypatch vs unittest.mock](#monkeypatch-vs-unittestmock)
- [Patch where the name is looked up](#patch-where-the-name-is-looked-up)
- [Always spec your mocks](#always-spec-your-mocks)
- [Small fakes](#small-fakes)
- [Time and randomness](#time-and-randomness)
- [Filesystem](#filesystem)
- [Async code](#async-code)
- [Over-mocking smells](#over-mocking-smells)

## Decision ladder

Work down; stop at the first rung that fits:

1. Real object — cheap, deterministic dependencies (dataclasses, pure helpers) need no substitute.
2. Fake — a small in-memory implementation of the interface. Best behavior-to-effort ratio for repositories, clocks, transports.
3. `monkeypatch` — swap one attribute, env var, or cwd for the test's duration.
4. `unittest.mock` — last resort, for asserting an interaction at a true boundary.

## monkeypatch vs unittest.mock

- `monkeypatch` (pytest fixture): `setattr`, `setenv`/`delenv`, `chdir`, `syspath_prepend`. Auto-undone after the test. Use for state swaps where no call assertion is needed.
- `unittest.mock.patch` / `mocker.patch` (pytest-mock): use when the test must assert how the boundary was called. Prefer the `mocker` fixture over decorator stacks — no argument-order coupling, auto-undone.
- `mocker` needs pytest-mock: check with `uv run python -c "import pytest_mock"`. If it is missing, ask before `uv add --dev pytest-mock`, or use `unittest.mock.patch` as a context manager; the examples below translate directly.

## Patch where the name is looked up

Patch the name in the module that *uses* it, not where it is defined.

```python
# app/greeting.py
from services.users import get_display_name


def greet(user_id):
    return f"Hello, {get_display_name(user_id)}"
```

```python
mocker.patch("services.users.get_display_name", ...)  # wrong: greeting already imported its own ref
mocker.patch("app.greeting.get_display_name", ...)  # right: patches the name greeting looks up
```

## Always spec your mocks

Unspecced mocks accept any attribute and any signature, so refactors silently pass.

```python
mocker.patch("app.greeting.get_display_name", autospec=True, return_value="Ada")
transport = mocker.Mock(spec=Transport)
```

`autospec=True` for patched callables, `spec=`/`spec_set=` for standalone mocks — always.

## Small fakes

A ten-line fake beats a mock with five configured return values:

```python
class FakeUserRepo:
    def __init__(self):
        self.saved = []

    def save(self, user):
        self.saved.append(user)

    def get(self, user_id):
        return next(u for u in self.saved if u.id == user_id)


def test_register_user_persists_user():
    repo = FakeUserRepo()

    register_user(repo, make_user(id="u1"))

    assert [u.id for u in repo.saved] == ["u1"]
```

The assertion is about real state, not mock bookkeeping, and the fake is reusable across the module's tests (promote to `conftest.py` when shared).

## Time and randomness

- Prefer injection: a `now: Callable[[], datetime]` parameter or clock object beats any patch. If the seam exists, use it.
- Otherwise patch at the use site: `mocker.patch("app.sessions.datetime", wraps=datetime)` with `now.return_value` fixed, or monkeypatch a module-level `_now()` helper.
- Randomness: inject a seeded generator where the code allows (`random.Random(0)`, `numpy.random.default_rng(0)`; `default_rng` returns a new generator to pass in and does not seed anything globally). Code that uses the global state needs global seeding in the test (`random.seed(0)`, `numpy.random.seed(0)`). Then assert on exact outputs, which the fixed seed makes deterministic.
- Never assert on wall-clock deltas or use `sleep` to wait for state.

## Filesystem

- `tmp_path` (per-test) and `tmp_path_factory` (per-session) for every file the test creates. Tests never write to the cwd, the repo, or a hard-coded path such as `/tmp/out.csv`; `/tmp` stays fine for the agent's own disposable experiments outside the test suite.
- Pass paths into the code under test; if it hard-codes paths, that is a seam to propose (see SKILL.md "When the code resists testing").

## Async code

- Use the project's existing async plugin (`pytest-asyncio` or `anyio`) — check `pyproject.toml`; don't introduce a second one.
- pytest-asyncio: `async def test_...` with `@pytest.mark.asyncio`, or the project's configured auto mode.
- AnyIO: `@pytest.mark.anyio` (or `pytestmark = pytest.mark.anyio` per module); the `anyio_backend` fixture selects the backend.
- Mock async boundaries with `mocker.AsyncMock(spec=Client)` — a plain `Mock` returns an unawaitable and fails confusingly at `await`.

## Over-mocking smells

Rewrite the test (or propose a seam) when you see:

- The only assertions are `assert_called*` — the test verifies wiring, not behavior.
- Patching private functions of the module under test — the test now mirrors the implementation and breaks on refactor.
- More than two nested patches for one Act — the boundary is wrong or the code needs a seam.
- The test still passes when the implementation body is replaced with `pass` — it tests the mocks, not the code. (The SKILL.md detection check catches this: it breaks the implementation and the test must fail.)
