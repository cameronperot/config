# Property-based testing with Hypothesis

Supplements SKILL.md for property-based tests. The SKILL.md workflow and validation loop still apply; this file only covers what changes when using Hypothesis.

## Contents

- [When properties pay off](#when-properties-pay-off)
- [Dependency](#dependency)
- [Property archetypes](#property-archetypes)
- [Strategy craft](#strategy-craft)
- [Shrinking and regression pinning](#shrinking-and-regression-pinning)
- [Determinism in CI](#determinism-in-ci)
- [Anti-patterns](#anti-patterns)
- [Validation](#validation)

## When properties pay off

Use property-based tests when the code has a relationship that must hold for all inputs:

- Round-trips: encode/decode, serialize/parse, `to_dict`/`from_dict`.
- Invariants: output sorted, totals preserved, length unchanged, no exception on any valid input.
- Oracles: a fast implementation checked against a slow-but-obviously-correct reference.
- Idempotence: `f(f(x)) == f(x)` — normalizers, formatters, sanitizers.
- Metamorphic relations: a known change to the input causes a predictable change to the output (e.g. doubling every quantity doubles the total).

Skip them for thin I/O wrappers, heavily mocked code, and functions whose contract is a call sequence — example-based tests say more there. Property tests complement example-based tests; keep explicit examples for documented behaviors and known edge cases.

## Dependency

Check availability: `uv run python -c "import hypothesis"`. If missing, ask the user before running `uv add --dev hypothesis`.

## Property archetypes

Round-trip:

```python
from hypothesis import given
from hypothesis import strategies as st


@given(st.dictionaries(st.text(min_size=1), st.integers()))
def test_config_roundtrip_decode_inverts_encode(payload):
    assert decode(encode(payload)) == payload
```

Oracle against a reference implementation:

```python
@given(st.lists(st.integers()))
def test_fast_sort_matches_sorted_builtin(xs):
    assert fast_sort(xs) == sorted(xs)
```

Invariant plus idempotence:

```python
@given(st.text())
def test_normalize_whitespace_is_idempotent(s):
    once = normalize_whitespace(s)

    assert normalize_whitespace(once) == once
```

## Strategy craft

- Build domain objects with `st.builds(User, age=st.integers(min_value=0, max_value=150))` or `@st.composite` when fields are interdependent.
- Constrain generation instead of filtering: `st.integers(min_value=1)` beats `assume(x > 0)`. Use `assume` only for rare, hard-to-express exclusions — heavy filtering slows generation and triggers health-check errors.
- `st.text()` generates control characters, combining marks, and other unusual code points by default (not surrogates, which it excludes). That is usually the point — but constrain the alphabet (e.g. `st.text(alphabet=st.characters(codec="ascii"))`) when the contract genuinely excludes such input, and say why in the test.
- Bound sizes (`max_size=`) for expensive operations so runs stay fast.

## Shrinking and regression pinning

- Hypothesis shrinks failures to a minimal example — report that minimal input, not the first noisy one, when filing a bug.
- Pin a previously found failure permanently with `@example(...)` above the `@given` so it runs on every invocation regardless of generation:

```python
@example("")
@given(st.text())
def test_normalize_whitespace_never_raises(s):
    normalize_whitespace(s)
```

## Determinism in CI

Register a deterministic profile once (e.g. in `conftest.py`) and select it in CI:

```python
from hypothesis import settings

settings.register_profile("ci", derandomize=True, max_examples=200)
```

Activate it with `settings.load_profile("ci")` in `conftest.py`, or pass `--hypothesis-profile=ci` to pytest. Hypothesis does not read a profile name from the environment by itself; to select one by variable, load it explicitly: `settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))`. Don't suppress health-check errors (`suppress_health_check=`) to make a flaky strategy pass — fix the strategy.

## Anti-patterns

- Re-implementing the function inside the property — the test becomes a tautology that can only agree with the code.
- Properties too weak to fail: asserting the result is a list, or not `None`. If no plausible bug could trip the assertion, it isn't a property worth testing.
- Cramming example-specific assertions into a `@given` body — put known cases in plain example-based tests or `@example`.
- Unbounded strategies on quadratic-or-worse code — bound sizes instead of raising deadlines.

## Validation

The SKILL.md validation loop applies unchanged, including its detection check: break the production code the property covers (e.g. drop a normalization step or flip a sign), confirm Hypothesis finds a counterexample, then restore. Never weaken the property itself; a weaker property is easier to satisfy, so it proves nothing.
