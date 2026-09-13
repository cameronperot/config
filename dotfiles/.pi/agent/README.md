# Pi Agent Configuration

The global Pi configuration, deployed to `~/.pi/agent/`. Everything here applies to every session in every directory.

Project-level files layer on top rather than replacing this: a repo's `AGENTS.md` / `CLAUDE.md` adds to [`AGENTS.md`](#agentsmd), and `<cwd>/.pi/guard-rules.json` may add restrictions to [`guard-rules.json`](#guard-policy).

## Layout

| Path | What it configures |
|---|---|
| `settings.json` | Provider, default model, default tool set, npm packages, TUI |
| `models.json` | Per-provider overrides — OpenRouter routing only |
| `guard-rules.json` | Path and bash-command policy the guard extensions enforce |
| `plannotator.json` | Plannotator's planning-phase instructions — the prompt spliced in while its planning mode is active |
| `AGENTS.md` | Prepended to every request; describes the extension tools and the subagent roles |
| `extensions/` | 21 local extensions plus shared modules — see [`extensions/README.md`](extensions/README.md) |

## Models and providers

The default provider, model and `thinkingLevel` live in `settings.json` and change often — read them there rather than assuming.

`models.json` carries one thing: OpenRouter routing pinned to `data_collection: deny` and `zdr: true`. That is a privacy floor for every request regardless of which model is selected, and it is kept separate from `settings.json` because it is provider policy rather than a preference. `enableInstallTelemetry` is off.

## Presets

The `preset` extension (`preset.ts`) reads named presets from `~/.pi/agent/presets.json`, with `<cwd>/.pi/presets.json` overriding by name, and switches provider, model, thinking level, tool set and instructions via `/preset`, `--preset` or Ctrl+Shift+U. A preset's `instructions` are appended to the system prompt while it is active, so they cost tokens only then.

No `presets.json` exists, so no presets are defined: every session runs the default provider and model from `settings.json`, and `/preset` reports "No presets defined". A preset that should be read-only achieves it by *construction* — it removes `edit` and `write` from its `tools` list rather than instructing the model not to use them.

## Modes

Session modes, all off or neutral at start and all toggles — running the command again turns the mode off, or pass an explicit `off`.

| Mode | Toggle | What changes |
|---|---|---|
| Plan (plannotator) | `/plannotator-plan-mode`, `--plan`, Ctrl+Alt+P | Plannotator's planning phase: writes gated to markdown files inside the working directory, bash prompt-guided, plan submitted via `plannotator_submit_plan` for browser review. From the npm package — see [Extensions](#extensions). |
| Preset | `/preset`, `--preset`, Ctrl+Shift+U | Swaps model, thinking level, tool set and instructions — see [Presets](#presets). |
| Approve | `/approve` | Confirms every `write` and `edit` before it runs. |
| Approve-all | `/approve-all` | Confirms every tool except `read`, `grep`, `find`, `ls`, `todo` and `questionnaire`. |
| Tool selection | `/tools` | Interactive checklist over the active tool set. Persists to the session, so a stale selection can override `defaultTools` on resume. |

The bundled `plan-mode/` extension — `/plan`, `/steps`, a read-only bash allowlist, `Plan:`-block step tracking — is staged as `extensions/plan-mode/index.ts.disabled` and does not load. The `--plan` flag and Ctrl+Alt+P shortcut it used to register now belong to plannotator; re-enabling it would overlap both.

Presets, plannotator's planning phase and `/tools` all drive the same active tool set, so use one at a time. The approve modes are a separate axis: they gate calls rather than removing tools, and they stay quiet when a guard is already going to block or ask about the same call, so turning one on can only add confirmations.

Together the modes cover three different controls. The planning phases **prevent** — plannotator gates writes to markdown inside the working directory, and plan-mode (when re-enabled) removes `edit` and `write` outright; the approve modes **confirm** at the moment of use; `/rewind` **undoes** after the fact. Note that both approve modes need a UI to ask through — under `-p` a gated call blocks instead, and the mode is restored from the session, so a resumed `/approve-all` session blocks every gated call.

## Guard policy

`guard-rules.json` is data; the extensions that enforce it are the mechanism. This global file defines policy. `<cwd>/.pi/guard-rules.json` may add restrictions, but cannot replace global rules or add zero-access exceptions. Put exceptions in the global file on the host.

| Class | Effect | What it covers here |
|---|---|---|
| `zeroAccessPaths` | Blocks direct reads, edits, explicit grep targets and literal bash references | Environment secrets, credential/auth data files, `*.key`, `*key.pem`, `*.priv`, `*.p12`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.netrc`, git credentials |
| `zeroAccessAllowPaths` | Exceptions to the above | `.env.example`, `.env-example`, `.env.template`, `.env.sample` |
| `readOnlyPaths` | Blocks write/edit; confirms suspected bash writes | Empty in the shipped policy; system and protected agent files are mounted read-only by the sandbox |
| `noDeletePaths` | Deletion and move-away refused | Empty in the shipped policy |
| `bashPatterns` | Regexes over the command string | Destructive `rm`, `sudo`, `chmod 777`; history-rewriting and work-discarding git; unqualified SQL `DROP` / `TRUNCATE` / `DELETE`; `curl \| sh`; `mkfs`; `dd of=/dev/` |

Severity belongs to the rule: `ask: true` prompts for confirmation, its absence blocks outright. All matching command rules are considered; hard blocks win, otherwise one prompt lists the matching reasons. A missing or malformed global policy falls back to a `SAFETY_FLOOR` in `extensions/shared/rules.ts` rather than to no protection.

In sandbox mode, standalone recursive cleanup of literal paths beneath `/tmp` runs without a rule confirmation, including quoted paths and missing targets whose existing ancestors resolve inside `/tmp`. Workspace cleanup remains gated. Host-oriented `sudo`, `mkfs` and raw-device rules are exempt in sandbox mode; downloaded scripts piped into a shell require confirmation. Optional `/approve-all` still gates exempt commands. See [sandbox exemptions](extensions/README.md#guard-policy) for the exact conditions.

Standalone unstaging with `git restore --staged`/`-S` and supported `git clean`/`git worktree prune` dry runs are exempt from their command rules. Quoted arguments to standalone `echo`, `printf`, `rg` and `grep` are treated as data when matching command rules. Interpreters, substitutions and pipelines retain conservative inspection; path guards still apply independently.

Sandboxed, nonrecursive permission and ownership changes on disposable `/tmp` files or directories are exempt from the `777` rule. Targets must exist on `/tmp`'s filesystem; special files and regular files with multiple hard links remain guarded. Recursive operations and workspace targets retain the existing guard.

These are speed bumps, not a security boundary. Recursive searches and indirection through `sh -c` or `python -c` can read protected files, and secrets held in **environment variables** cannot be protected at all — `bash` inherits the process environment. Source files such as `auth.ts`, public certificate filenames such as `server.pem`, and `.envrc` are accessible; filenames cannot determine whether their contents are secret. See [Known gaps](extensions/README.md#guards).

## Subagents

`subagent` reads role definitions from `~/.pi/agent/agents/*.md` (user scope) and the nearest `.pi/agents/` directory up the tree (project scope), with `user` the default; on a name conflict under the `both` scope the project definition wins. Ten roles are defined, matching the descriptions in [`AGENTS.md`](#agentsmd): scout, docs-researcher, planner, engineer, linter, test-runner, debugger, reviewer, security-auditor, pr-summarizer — see [`agents/README.md`](agents/README.md) for tool grants, model pins and output contracts.

A role is a Markdown file with `name` and `description` frontmatter, optional `tools` and `model`, and a system-prompt body. Three constraints are worth planning around: `tools` becomes a strict allowlist for the child, so a role without `bash` cannot run commands and a role without `subagent` cannot delegate further; a child cannot see the parent conversation and the parent cannot see the child's, so each task must be self-contained; and a `model:` string is passed to the child as `--model` and needs the provider prefix (`provider/model`). The agent name must match a defined role exactly, since an unknown name is rejected rather than guessed at.

Headless children cannot answer confirmation prompts. The guards return an approval request containing the exact tool input, cwd and reason; the subagent extension preserves it even if the child's final response omits it. Such runs are reported as needing approval and stop dependent chain steps. The parent handles approval and execution through its normal guards before delegating remaining work; no child permission is granted automatically.

## AGENTS.md

Prepended to every request, which is why it is kept short. It carries the one thing Pi's default system prompt does not: that `todo`, `questionnaire` and `subagent` exist, and when to reach for them. A model that is not told about a tool will not call it.

`defaultTools` in `settings.json` is the initial active set — `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`, `todo`, `questionnaire`, `subagent` — and lists all three, so `AGENTS.md` holds true in a session with no preset. Registering a tool is not the same as activating it.

## Extensions

Twenty-one extensions load from `extensions/` (`plan-mode/` is staged disabled and does not load), plus two npm packages installed via `packages` in `settings.json`.

| Group | Extensions | Adds |
|---|---|---|
| Guards | `permission-gate`, `protected-paths`, `protected-paths-bash`, `approve-gate` | `/approve`, `/approve-all` |
| Tools | `built-in-tool-renderer`, `todo`, `questionnaire` | tools `todo` `questionnaire`; `/todos`, `/read-log` |
| Workflow | `preset`, `tools`, `handoff`, `commands`, `subagent/` | tool `subagent`; `/preset`, `/tools`, `/handoff`, `/commands` |
| Git | `worktree` | `/worktree`, `pi --gwt <name>` |
| Display | `custom-footer`, `notify`, `system-prompt-header` | `/footer` |
| Context | `claude-rules`, `rules-loader`, `shake` | `/shake`, `/unshake` |
| Session | `session-name`, `bookmark` | `/session-name`, `/bookmark`, `/unbookmark` |
| npm | `pi-rewind` 0.5.0, `@plannotator/pi-extension` 0.27.9 | `/rewind`, Esc Esc; `plannotator_submit_plan` tool, `/plannotator-plan-mode`, `/plannotator-review`, `/plannotator-annotate`, `/plannotator-last`, `--plan`, Ctrl+Alt+P |

Mechanism, per-request token cost, known gaps, local modifications and extension interactions are in [`extensions/README.md`](extensions/README.md).
