# Pi Sub-Agents

Ten sub-agent definitions for the Pi coding harness, loaded by this repo's [subagent extension](../extensions/subagent/index.ts). `install.py` deploys the definitions to `~/.pi/agent/agents/` and the extension to `~/.pi/agent/extensions/subagent/`. The `agents` directory is included in the `.pi/agent` scope in `dotfiles.yaml`.

## How the extension runs agents

Each invocation starts a separate Pi process with its own conversation context, using the current executable when possible. The effective arguments are:

```
pi --mode json -p --no-session [--model <model>] [--thinking <level>] [--tools <tools>] --append-system-prompt <temporary-prompt-file> "Task: ..."
```

Consequences for the agent files:

- Frontmatter fields the extension reads: `name` and `description` (required strings) and `tools` / `model` (optional). Any other field (e.g. `thinking`, `systemPromptMode`) is ignored.
- `description` is what the parent agent sees when deciding which agent to delegate to — keep it specific about when to use the agent and what it returns.
- The markdown body is written to a temporary file and appended to Pi's system prompt. AGENTS.md context files, skills, and extensions still load; this README is not appended as shared agent instructions.
- `model` is passed through to Pi, including any `:<thinking>` suffix. Without a `model` field, the extension passes the dispatching session's model and thinking level. With a model pin, it does not separately pass `--thinking`. There is no dedicated `thinking` frontmatter field.
- `tools` is a strict allowlist over built-in, extension, and custom tools. Names that aren't registered are silently ignored (they do not cause an error).
- Agents run in the dispatching session's working directory, or an explicit `cwd` per task. Separate processes share the workspace; they do not get separate checkouts or filesystems.
- None of these definitions grants `todo`, `questionnaire`, or `subagent`. Children return material questions and suggested handoffs in their final output; the parent handles interaction and further delegation.

## Install

- User scope (all projects): `~/.pi/agent/agents/` — what this repo deploys.
- Project scope: the nearest `.pi/agents/` directory found by walking upward from the dispatching session's working directory. The default scope is user-only; `agentScope: "both"` enables project overrides by name, and `"project"` selects only project agents. With a UI and `confirmProjectAgents` enabled (the default), the extension asks before each invocation that selects project agents; it does not store a first-use trust decision.

## Agents

| Agent | Tools | Source edits? | Purpose |
|---|---|---|---|
| scout | read, grep, find, ls | No | Codebase recon → compact map |
| docs-researcher | read, grep, find, ls | No | Version-aware API/spec brief from available sources; external verification gaps |
| planner | read, grep, find, ls | No | Minimal numbered implementation plan |
| engineer | read, grep, find, ls, bash, edit, write | Yes | Implements a plan/task: writes code, runs tests |
| linter | read, grep, find, ls, bash, edit | Yes (existing files only; check-only supported) | Python lint/format/type fixes using py-lint-fix and py-typecheck |
| test-runner | read, grep, find, ls, bash | No | Existing tests/builds, results and failure triage |
| debugger | read, grep, find, ls, bash, edit | Yes (existing files only) | Reproduce → isolate → fix one bug |
| reviewer | read, grep, find, ls, bash | No | Independent severity-ranked review |
| security-auditor | read, grep, find, ls, bash | No | Vulnerability audit with attack scenarios |
| pr-summarizer | read, grep, find, ls, bash | No | PR/commit summary from git diff |

`scout`, `docs-researcher`, `test-runner`, and `pr-summarizer` pin `openrouter/z-ai/glm-5.3-flash:low`; `engineer` and `linter` pin `openrouter/z-ai/glm-5.3-flash:max`; `planner`, `debugger`, `reviewer`, and `security-auditor` pin `openrouter/z-ai/glm-5.3:high`. These are configured model choices, not a guarantee of provider availability. Remove `model:` to inherit the dispatching session's model and thinking level.

## Dev-container boundaries

- The [dev-container setup](../../../../dev-container/README.md) routes agent commands through `agent-sandbox`. Children inherit the parent's sandbox: the workspace is writable, system and agent configuration paths are restricted, and network access remains shared. The dispatching working directory is not necessarily `/work`; `c` preserves the mounted project path.
- The image provides tools including `git`, `rg`, `fd`, `curl`, `uv`, and the micromamba `dev` environment. Availability in the image does not grant an agent shell access. Use project-defined commands and check their prerequisites; do not assume host services or credentials are available. The sandbox does not expose host `gh` authentication.
- `docs-researcher` has neither shell nor web tools. It can inspect local or supplied source content and return precise requests for external verification to the parent. Live web research requires a separately authorized tool/configuration change.
- Read-only roles with `bash` rely on their instructions to restrict command side effects; the allowlist is not a read-only shell sandbox. Test-runner and reviewer may produce ordinary check artifacts, but must not edit source, configuration, or snapshots. Debugger and linter edit existing files only; engineer can create files.
- Guard extensions still apply in children. Commands requiring guard confirmation are blocked in headless mode; the child reports the denial to the parent rather than attempting an interactive prompt or bypass.

## Handoffs

Give each task its scope, expected behavior, relevant findings, and acceptance criteria; children cannot see the parent's conversation. For review or summarization, specify refs or which working-tree changes to include. Only the child's final output is forwarded as the textual result, so it must include verification evidence and blockers.

A typical sequence is scout → planner → engineer (or implementation in the parent) → test-runner → reviewer. Use linter for Python lint and type diagnostics, debugger for a concrete failure, security-auditor for security-sensitive scope, docs-researcher for source verification, and pr-summarizer for the final draft. In chain mode, include `{previous}` in a task to pass the preceding child's final output; earlier task context is not carried forward automatically. The parent must inspect blocked or partial results before continuing: a process can exit successfully even when its final text reports incomplete work.
