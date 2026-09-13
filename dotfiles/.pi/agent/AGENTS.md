# Global Agent Notes
## Environment

When launched through `agent-sandbox`, system files and protected agent configuration are read-only, while the workspace, Git metadata, and agent state remain persistent and writable. You may inspect the repository and exposed documentation, configuration, and toolchains beyond the current working directory. Keep project changes within the task's scope. Use `/tmp` for disposable experiments and build output; changes there disappear when the sandbox exits. If a required resource is unavailable, report it rather than attempting to bypass isolation. Do not assume direct or explicitly unsandboxed launches have these protections.

## Extension Tools

Beyond the built-ins, three tools are registered and active by default:

- `todo` — track multi-step work as a checklist; keep it current as steps complete.
- `questionnaire` — ask the user structured questions. Use it instead of guessing when requirements are ambiguous.
- `subagent` — delegate a task to a child agent with its own context window; its final output or outstanding approval requests return here.

## Subagent Roles

- `scout` — read-only codebase recon; maps relevant files, entry points, data flow, and risks before implementing or planning.
- `docs-researcher` — read-only research on external libraries, APIs, and specs; returns a sourced, version-aware brief.
- `planner` — read-only; turns requirements plus scout findings into a minimal, numbered, verifiable implementation plan.
- `engineer` — implements a concrete plan or task: writes/edits code, runs tests; write-capable implementation agent (cheap model, max thinking effort).
- `linter` — lints, formats, and typechecks Python using `py-lint-fix` and `py-typecheck`; fixes existing files within scope and honors check-only requests.
- `test-runner` — runs the project's existing tests/build and returns a structured pass/fail triage; never edits source.
- `debugger` — diagnoses and fixes one specific bug (reproduce → isolate → fix → verify); edits files but does not implement features.
- `reviewer` — independent severity-ranked code review of a diff/change for correctness, security, and maintainability.
- `security-auditor` — read-only security audit of specified code/diff; reachable vulnerabilities with attack scenarios and remediation.
- `pr-summarizer` — generates a PR/commit title and summary from the current git diff.

Children cannot see this conversation and cannot delegate further — make each task well-defined and self-contained.

When a child reports an approval request, review the exact tool input and working directory. Present the action through the parent's normal approval guards, execute it only after approval, then delegate any remaining work. Do not repeatedly send the blocked action back to a headless child. Hard policy blocks still require a policy decision from the user; they are not approval requests.
