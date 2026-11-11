# Change Discipline
Every change must serve the given task — nothing more.

## Scope
- Change only what the request requires. Do not refactor, reformat, or "improve" adjacent code, even where it is clearly better.
- Match the patterns of the surrounding code and the nearest existing module, even where you would choose differently in new code.
- Create files only where the task requires them (tests for the code the task changes count); no unrequested docs, READMEs, examples, or scripts.
- Introduce no new dependencies without asking.
- Clean up only the dead code and orphaned imports your own changes created.
- Mention anything worth fixing outside the request, but only fix it if instructed to.
- If a task turns out to require work beyond its stated scope, stop and ask before expanding it.

## Simplicity
- No unrequested features.
- No abstraction or indirection for code used in only one place.
- No error handling for scenarios that cannot occur in the current codebase; no defensive coding against impossible states.
- Fail loudly: never write code that swallows errors, masks issues, or degrades silently unless explicitly asked.
- Add backwards compatibility only when explicitly requested; ask if unsure.
- Leave no comments referencing removed or replaced logic (e.g. "legacy behavior").

## Smell Tests
- "Would a senior engineer call this overcomplicated?" → simplify.
- "Could this be written in significantly fewer lines without losing clarity?" → rewrite.
