# Pi Extensions

Extensions for Pi. Pi loads `*.ts` / `*.js` at this level plus `*/index.ts` subdirectories, so `README.md`, `package.json` and `tsconfig.json` are inert and `shared/` is a plain module directory rather than an extension.

## Contents

The extensions themselves, by what they do:

- [Guards](#guards) — `permission-gate.ts`, `approve-gate.ts`
  - [Guard policy](#guard-policy) — the `guard-rules.json` classes they enforce
- [Tools](#tools) — `built-in-tool-renderer.ts`, `todo.ts`, `questionnaire.ts`
- [Workflow](#workflow) — `preset.ts`, `tools.ts`, `handoff.ts`, `commands.ts`, `subagent/`
  - [Subagent roles](#subagent-roles) — where `subagent/` reads its agent definitions (ten, in `~/.pi/agent/agents/`)
- [Worktree](#worktree) — `worktree.ts`
- [Display](#display) — `custom-footer.ts`, `notify.ts`, `system-prompt-header.ts`, `system-prompt-dump.ts.disabled`
- [Context](#context) — `claude-rules.ts`, `rules-loader.ts`, `shake.ts`
- [Session](#session) — `bookmark.ts`
- [npm packages](#npm-packages) — `pi-rewind` and `@plannotator/pi-extension`, installed rather than staged here

Across all of them:

- [Per-request token cost](#per-request-token-cost) — what reaches the model on every request
- [Local modifications](#local-modifications) — where these diverge from the shipped examples
- [Interactions](#interactions) — conflicts to know about when combining them

## Guards

The guards are the *mechanism*; the policy they enforce is data, in [`guard-rules.json`](#guard-policy).

| Extension | What it does | Registers |
|---|---|---|
| `permission-gate.ts` | Enforces path and command policy for `read`, `write`, `edit`, `grep` and `bash`, using `shared/rules.ts`. Hard blocks win; otherwise one confirmation lists all reasons. | — |
| `approve-gate.ts` | Two opt-in modes, both off by default: `/approve` confirms every `write`/`edit`, `/approve-all` confirms every tool bar the read-only ones. | `/approve`, `/approve-all` |

`permission-gate.ts` is the single policy-enforcement extension. `approve-gate.ts` adds optional confirmations for otherwise permitted side effects and uses the same policy decision implementation to defer to policy blocks or confirmations. Neither optional mode prompts for `read`, `grep`, `find`, `ls`, `todo` or `questionnaire`. `/approve-all` gates every `bash` call, including commands that only read.

`subagent` runs headless in its own context, so `/approve-all` gates delegation before the child starts. The child's guard confirmations return to the parent as approval requests; ordinary ungated child tool calls do not prompt individually.

The central guard records blocked read and bash access through `shared/access-log.ts`; `built-in-tool-renderer.ts` records allowed reads and provides `/read-log`. Tool rendering contains no policy checks.

Every block and every answered confirmation — including a blocked `read` — is appended to the session as a `guard-block` entry (`{tool, rule, action, detail}`), so a blocked write leaves a trace after the notification scrolls away. Block text tells the model not to route around the block; without that a refusal reads as a failed attempt and `cat` becomes `head` becomes `python -c`.

**Known gaps.** These are speed bumps, not a security boundary:

- Path matching tokenizes the command on shell metacharacters, so indirection defeats it — `sh -c`, `python -c`, base64, or a path built from a variable.
- Recursive `grep` or shell searches can read protected files without naming them as the search target. Paths are matched by spelling, not by resolving symlinks. Filename guards cannot identify secrets in otherwise permitted files such as `.envrc` or `server.pem`.
- Secrets held in **environment variables** cannot be protected at all. The `bash` tool inherits the process environment and `echo $TOKEN` is indistinguishable from any other `echo`. Anything in the environment is readable by the agent; treat it that way when deciding what to export.
- Overriding a built-in tool does **not** bypass the guards: `tool_call` fires on the tool *name*, before execution, regardless of which implementation backs it.

## Guard policy

Global policy comes from `~/.pi/agent/guard-rules.json`. `<cwd>/.pi/guard-rules.json` may append path restrictions and command rules, but cannot clear global classes or add `zeroAccessAllowPaths`. Project exceptions are ignored with a warning through the UI or headless stderr; edit global policy on the host to permit an exception. Policy is cached per cwd for the process lifetime.

| Class | Effect |
|---|---|
| `zeroAccessPaths` | Blocks direct read/write/edit, explicit grep targets and literal bash references. |
| `zeroAccessAllowPaths` | Exceptions only to zero-access policy; independent read-only and no-delete rules still apply. |
| `readOnlyPaths` | Reads fine; `write`/`edit` blocked and suspected bash writes confirmed. |
| `noDeletePaths` | Deletion and move-away refused. |
| `bashPatterns` | `{pattern, reason, ask?, sandboxExemption?, commandExemption?}` regexes over the command string. |

Severity is a property of the rule: `ask: true` prompts, its absence blocks. Every matching rule is considered: any hard block wins; otherwise a single confirmation lists all matching reasons. Common Git global options (`-C`, `-c`, `--git-dir`, `--work-tree`, `--no-pager`, `--paginate`, `--bare`, `--no-optional-locks`) are also matched after normalization. This remains a heuristic, not a shell parser. Rules that ask still block when there is no UI to ask through. Path classes carry no per-rule `ask` flag, and `zeroAccessPaths` and `noDeletePaths` always block.

`sandboxExemption` accepts `host`, `tmp-cleanup` or `tmp-permissions`. Exemptions apply only when the process starts with `AGENT_SANDBOX_ACTIVE=1` and no nonempty `AGENT_SANDBOX_DISABLE`. This trusts the wrapper's mode indicator; it is not independent proof of isolation, so do not export the active marker on the host. `host` skips the annotated `sudo`, `mkfs` and raw-device rules. `tmp-cleanup` skips annotated deletion rules only for a literal `rm` segment with `-r`/`-R`/`-f` combinations, `--recursive`, `--force`, or `--`, and literal targets beneath `/tmp`. Single and double quotes, spaces inside quoted paths, and missing targets are supported. The nearest existing ancestor must resolve inside `/tmp`; dangling symlinks, symlinks escaping `/tmp`, `..` components and deletion of `/tmp` itself retain confirmation. Shell expansions, unquoted globs, escapes and unsupported syntax retain conservative inspection. The exemption never overrides another matching rule or `/approve-all`. Use `/tmp` for disposable builds; project output directories are not automatically disposable.

`tmp-permissions` exempts the annotated permission/ownership rule for literal, nonrecursive `chmod` and `chown` calls on literal existing files or directories beneath `/tmp`. Targets must pass the temporary-path check and be on `/tmp`'s filesystem; regular files must have only one hard link. Special files, other filesystems, shared hard links, missing targets and recursive operations retain the guard. Verbose, changes-only and quiet flags (`-v`, `-c`, `-f` and their long forms), quoting and `--` are supported. Other modes of `chmod`/`chown` remain subject to whichever policy rules match; the shipped rule specifically matches commands involving `777`.

`commandExemption` accepts `git-index` or `git-dry-run`, independently of sandbox mode. The shipped restore rule permits literal `git restore --staged` or `-S`, optionally with `--quiet`/`-q`, and literal paths. Any other option, including worktree restoration, retains the guard. Clean and worktree-prune rules permit literal `--dry-run`/`-n` commands with supported verbosity/clean flags; unknown or negated options retain the guard. Exemptions apply only to their annotated rules, so project restrictions and `/approve-all` still apply.

Literal sequences separated by `&&`, `||` or `;` are inspected segment by segment, so an exempt first command never exempts a destructive second command. `rm -rf /tmp/pi-review-scratch && true` is permitted only in sandbox mode; `git restore --staged src/file.ts && git status` is permitted in either mode. Existing temporary-target symlink, traversal, filesystem and hard-link checks still apply.

Quoted print data and search strings are distinguished from executable code. Bounded `rg`/`grep` forms support a positional pattern, simple `-inlqsvwFx` flags and `--`; file-content targets still obey zero-access policy. Literal `test -f/-d/-e/-L/-s PATH` and `git check-ignore PATH...` inspect metadata without reading file contents. Thus `rg '.env' README.md`, `test -f .env` and `git check-ignore .env` are allowed. Literal pipelines into `head`, `tail`, `wc`, `uniq` or `cat` are understood, including `rg 'DROP DATABASE' migrations | head`. Executable consumers, `rg --pre`, interpreters such as `bash -c` and `psql -c`, substitutions, expansions, escapes, multiline commands and unsupported options retain conservative inspection.

The shipped zero-access exceptions include environment templates and public SSH files `~/.ssh/allowed_signers` and `~/.ssh/*.pub`. The SSH exceptions have matching read-only rules: `read`/`grep` and `cat` are allowed, `write`/`edit` are blocked, and suspected bash modifications need confirmation. Private keys, `.env.test` and fixture credential files remain guarded; there is no general fixture exemption.

When no UI is available, a confirmation returns an `Approval required (no UI)` result with exact tool input, cwd and reason. `shared/approval.ts` collects these from failed tool-result messages. The subagent extension includes outstanding requests in returned text and `approvalRequests` details, reports those children as needing approval, and stops dependent chain steps even if the child exits successfully or omits the request from its final text. The parent must use its normal approval guards to execute the action in the stated cwd before delegating remaining work. This does not approve anything automatically or convert hard blocks into approval requests.

Matching is per **path segment**, with `*`/`?` confined to one segment, `~` expanded, and relative patterns matching a contiguous run of segments at any depth, so `node_modules/` catches it however deep it is nested.

`shared/rules.ts` holds a small `SAFETY_FLOOR`. A missing, malformed or partial global policy falls back to it, and the problem is announced once per cwd through UI notifications or stderr in headless mode, preserving structured stdout. A class the global file omits keeps the floor's value; a class it states replaces the floor's, so it can be narrowed on purpose. Invalid command regexes retain the fallback command rules. Malformed project policy leaves global protection active.

Run the guard regression tests from the repository root with `node --test tests/test_pi_guards.mjs` (tested with Node 26.5.1). They exercise the guard modules with a mocked Pi UI, without starting an agent or contacting a provider. Run `npm run typecheck` from this directory to check against the installed Pi types.

## Tools

| Extension | What it does | Registers |
|---|---|---|
| `built-in-tool-renderer.ts` | Display for the four core tools, through `shared/render.ts`; `read` additionally logs allowed access to `~/.pi/agent/read-access.log`. Policy blocks and blocked-access logging occur in `permission-gate.ts` before execution. | tools `read` `bash` `edit` `write`, `/read-log` |
| `todo.ts` | Todo list the model maintains; state lives in tool-result details so it stays correct across `/tree` branches. Renders through `shared/render.ts` like the core four. | tool `todo`, `/todos` |
| `questionnaire.ts` | Lets the model ask *you* structured questions — options plus free text, tab bar for multi-question forms. | tool `questionnaire` |

`shared/render.ts` holds the display grammar those five share: a **call row** (Nerd Font glyph, tool name, primary argument), a **body** bounded to a line budget and set behind a `│` gutter or a line-number column, and a **status row** carrying outcome, size and elapsed time. `renderDiff` paints the diffs, `highlightCode` the commands and previews, `keyHint` the expand hint — so the kit adds no dependency. Budgets sit in one `PREVIEW` table (bash output 10 lines, write preview 6, read preview 3, diff 40, todo 8, expanded 12) and `ctrl+o` lifts them. They are applied before wrapping and before highlighting, not after: a 2000-line result then costs the renderer its budget rather than its length, which matters because a running tool repaints on every spinner tick.

Two choices are worth knowing. Glyphs are Nerd Font with no ascii fallback, and the first thing to change if the agent is ever driven from a plain-font terminal. And none of the five draws a frame: Pi's default tool shell already supplies the padding and the pending/success/error background tint, so `edit` sets `renderShell: "default"` explicitly, since omitting it inherits the built-in's `"self"` and loses the tint.

## Workflow

| Extension | What it does | Registers |
|---|---|---|
| `preset.ts` | Named presets from `~/.pi/agent/presets.json` setting provider, model, thinking level, tool set and instructions. | `/preset`, `--preset`, Ctrl+Shift+U |
| `tools.ts` | Interactive checklist to enable/disable tools mid-session; persists to the session and restores on start and on `/tree` navigation, reporting excluded tools. | `/tools` |
| `handoff.ts` | `/handoff <goal>` summarises the session into a self-contained prompt and opens it in a fresh session. Non-lossy alternative to `/compact`. Costs one LLM call. | `/handoff` |
| `commands.ts` | Lists every slash command, filterable by source. | `/commands` |
| `subagent/` | Delegates a task to a child `pi` process with its own context window; returns final output or outstanding approval requests. Single, parallel (max 8, 4 concurrent) and chain modes. | tool `subagent` |

## Worktree

| Extension | What it does | Registers |
|---|---|---|
| `worktree.ts` | Git worktree management. Worktrees live in a sibling folder (default `../.worktrees/<repo>/<name>`) so the main checkout stays clean; in a `.bare` layout (`.bare/` plus sibling worktrees, as `git-bareify` produces) they are created next to `.bare`. Each worktree's session directory is symlinked to the main worktree's, so `/resume` lists sessions from all of them alike. The extension never prunes: entries git reports as prunable show as `missing` in `list`, and `create`, `--gwt` and `remove` ask before removing that single stale entry (its directory may only be unmounted in a container or sandbox). Config: `~/.pi/agent/worktree.json` (global) or `<main-worktree>/.pi/worktree.json` (repo, trust-gated) — `root`, `copyFiles`, `setupCommand`. | `/worktree create\|list\|remove\|open`, `pi --gwt <name>` |

## Display

| Extension | What it does | Registers |
|---|---|---|
| `custom-footer.ts` | Footer with live `↑input ↓output $cost` summed from session usage, plus model id and git branch. **Off until you run `/footer`.** | `/footer` |
| `notify.ts` | Desktop notification when the agent finishes — OSC 777 (Ghostty/iTerm2/WezTerm), OSC 99 (Kitty), WSL toast. Interactive sessions only. | — |
| `system-prompt-header.ts` | Status widget showing system prompt length in chars — a watchdog on prompt bloat. | — |
| `system-prompt-dump.ts.disabled` | **Not loaded** — renamed so Pi's loader skips it. When re-enabled, it appends the **full** system prompt to `~/.pi/agent/system-prompt.log` on every model request; `/system-prompt` prints the current one to standard out. | `/system-prompt` |

## Context

| Extension | What it does | Registers |
|---|---|---|
| `claude-rules.ts` | Lists `<cwd>/.claude/rules/*.md` **paths** in the system prompt; the agent reads a rule only when it needs it. Project-scoped — does **not** pick up `~/.claude/rules/`. | — |
| `rules-loader.ts` | Splices the **full text** of `~/.agent/rules/*.md` into the system prompt inside the first AGENTS.md `<project_instructions>` block, so the rules read as a continuation of it; appended at the end when no AGENTS.md block is present. A no-op when the directory is missing or empty. | — |
| `shake.ts` | Replaces old tool results with short stubs in the payload sent to the model, leaving the transcript intact. Manual only. | `/shake`, `/unshake` |

`rules-loader.ts` is the counterpart to `claude-rules.ts` by intent, not mechanism: `claude-rules.ts` serves project rules on demand (paths only, read when needed), while `rules-loader.ts` inlines rules that must hold in every session — the Behavior and Change Discipline sections formerly inline in `~/.pi/agent/AGENTS.md`, now split into `~/.agent/rules/*.md` with one concern per file. Splicing inside the `<project_instructions>` block keeps the rules at the same standing as the agent notes instead of dangling after the prompt. `~/.agent/` is not a Pi directory, and the per-request cost is the house pattern's: full rule text on every request. Rules are read once per `session_start`, so edits land only after a restart.

`shake.ts` is non-destructive by construction: the `context` handler is a pure transform that core applies on the way to the provider and never writes back, so the session file, the TUI rendering and `/export` keep the full text. The only state is a set of shaken tool-call ids. Selection skips the newest 20k tokens, results under 200 tokens, and results containing images, and `/shake` refuses unless it reclaims at least 2k tokens.

Two consequences to plan around. Rewriting an old message invalidates the provider's prompt cache from that point onward — the 2k floor exists so a marginal shake cannot cost more in re-read prefix than it saves, and it is why automatic shaking on a context threshold is deliberately not wired up. And state is per-process, so resuming a session starts unshaken.

## Session

| Extension | What it does | Registers |
|---|---|---|
| `bookmark.ts` | Labels entries so they stand out in `/tree`. | `/bookmark`, `/unbookmark` |

## Subagent roles

`subagent/` reads its agent definitions from `~/.pi/agent/agents/*.md` (user scope) and the nearest `.pi/agents/` directory up the tree (project scope), outside this directory. Ten roles are defined in `~/.pi/agent/agents/` — scout, docs-researcher, planner, engineer, linter, test-runner, debugger, reviewer, security-auditor, pr-summarizer — matching the descriptions in `../AGENTS.md`; tool grants, model pins and output contracts are tabulated in [`../agents/README.md`](../agents/README.md). On a name conflict under the `both` scope, the project definition wins.

A `tools:` list in frontmatter becomes the child's `--tools` allowlist, so a role without `subagent` cannot recurse and a role without `bash` cannot run commands. A `model:` string is passed to the child as `--model` and needs the provider prefix (`provider/model`) — all ten roles pin one.

## npm packages

| Package | Version | What it does | Registers |
|---|---|---|---|
| `pi-rewind` | 0.5.0 | Git-based checkpoints per turn, restore via `/rewind`. MIT, zero dependencies, registers **no tools**. | `/rewind`, Esc Esc |
| `@plannotator/pi-extension` | 0.27.9 | File-based plan mode with browser review: the agent drafts the plan as a markdown file and submits it via `plannotator_submit_plan` for annotation and approval. While planning, writes are gated to markdown inside the working directory. Also `/plannotator-review` (code review) and `/plannotator-annotate`. | `plannotator_submit_plan` tool, `/plannotator-plan-mode`, `/plannotator-review`, `/plannotator-annotate`, `/plannotator-last`, `--plan`, Ctrl+Alt+P |

Installed via `packages` in `../settings.json` rather than as a file here.

## Per-request token cost

Everything that reaches the model on every request, as opposed to on demand:

| Source | Cost | Notes |
|---|---|---|
| `read` `bash` `edit` `write` | none | Re-registrations of the built-ins with the same descriptions and schemas. |
| `todo` `questionnaire` `subagent` | ~350 tokens total | Three genuinely new tool definitions. |
| `claude-rules.ts` | one line per rule file | Only in a cwd that has `.claude/rules/`. |
| `rules-loader.ts` | full text of `~/.agent/rules/*.md` (~3 KB here) | Always-on global rules, in every request. |
| `preset.ts` | length of `instructions` | Only while a preset is active. |
| plannotator (npm) | planning-phase `instructions` from `plannotator.json` plus the `plannotator_submit_plan` tool definition | Only while a plannotator phase is active — the tool is added to the active set for the phase and released after. |
| `shake.ts` | negative | Removes tokens rather than adding them. Its `context` handler runs before every request, so it stays O(messages) with no I/O. |
| `system-prompt-dump.ts.disabled` | none | Renamed to `.disabled`, so it does not load. |

Everything else registers commands, shortcuts or renderers only, and costs nothing per request.

Nothing in Pi's default system prompt mentions `todo`, `questionnaire` or `subagent`, so a model that is not told about them will not call them; `../AGENTS.md` carries that description. On the verified Pi 0.85.1 runtime, `defaultTools` selects the seven built-ins while fresh sessions also activate registered extension tools. Explicit tool allowlists and restored selections still restrict activation.

## Local modifications

These diverge from their `examples/extensions/` counterparts:

- **`built-in-tool-renderer.ts`** — merged with the shipped `tool-override.ts`, which registered a competing `read`. The merged `read` delegates to `createReadTool()` rather than a hand-rolled implementation, builds base tools per `ctx.cwd` with the settings core passes in `_buildRuntime`, and logs allowed read access. Policy enforcement belongs to `permission-gate.ts`. All four renderers were then rewritten onto `shared/render.ts`: the shipped ones printed an unstyled dim block under a hardcoded 15/20/30-line cap, and read the bash exit code with `/exit code: (\d+)/` — a string core never emits, so every failed command rendered as a green `done`. Outcome now comes from `context.isError` plus core's `Command exited with code N` / `timed out after N seconds` / `aborted` trailer, which is stripped off the body rather than repeated in it.
- **`todo.ts`** — renderers rewritten onto `shared/render.ts`. The shipped version printed a five-item `✓`/`○` list for `list` and a different one-line summary for every other action; this one always shows the list as a tree with a done count, so a `toggle` shows what it toggled in context.
- **`notify.ts`** — returns early unless `ctx.hasUI`. `subagent/` spawns children with extensions loaded, and their stdout is the JSON protocol stream the parent parses; an OSC sequence written there corrupts whichever event line it lands in.
- **`permission-gate.ts`** — rule-driven rather than carrying their path lists and regexes as source literals, with the `ask` distinction, the audit entry, and path-segment matching added.
- **`shared/rules.ts`**, **`shared/access-log.ts`**, **`shared/render.ts`**, **`shake.ts`** and **`approve-gate.ts`** — authored here, no upstream equivalent.
- **`system-prompt-dump.ts`** — authored here, no upstream equivalent. Currently staged as `system-prompt-dump.ts.disabled`, so it does not load. The `context` hook (before every model call) calls `ctx.getSystemPrompt()` and appends the prompt to `~/.pi/agent/system-prompt.log`; `/system-prompt` prints the current prompt to stdout on demand. It writes to a file rather than the TUI/console because the prompt is large and a per-call dump into a live render or a `-p` protocol stream would be unusable. Note `ctx.getSystemPrompt()` reflects Pi's system prompt, not provider-payload rewrites other extensions make later in the chain.

Two shipped examples were staged and later removed: `inline-bash.ts` (its `!{cmd}` expansion runs through `pi.exec`, which is not a `tool_call`, so it bypassed every guard on this page including plan mode) and `modal-editor.ts` (it swallowed the first Escape, breaking single-Escape abort, `doubleEscapeAction` and `pi-rewind`'s Esc Esc at once).

## Interactions

- `preset.ts`, `tools.ts` and plannotator's phase profiles all drive `setActiveTools()`. Use one at a time. `tools.ts` additionally restores its saved set on `session_start` and on `/tree` navigation, so a saved selection can override `defaultTools` on resume. Restoration reports exclusions; use `/tools` to change the selection.
- Clearing a preset with no snapshot to restore falls back to `read, bash, edit, write` — narrower than the configured `defaultTools`. Use `/tools` to get the rest back.
- Duplicate tool and command names resolve to whichever loads first, and load order is unsorted `readdir`. Extension commands shadow same-named prompt templates; Pi's built-ins win over both. Plannotator provides planning commands; no local `/plan` or `/steps` extension is shipped.
- `approve-gate.ts` is **additive** to the other guards, not layered over them: all `tool_call` handlers run in sequence, the first to block wins and the rest never run, and load order is unsorted `readdir`. Because that order is not controllable, the gate calls the shared policy decision implementation before prompting and stays quiet when a guard is going to block or ask about the same call — so a call `guard-rules.json` refuses is never presented for approval, and an `ask` rule produces one prompt rather than two. Turning a mode on can therefore only ever *add* confirmations.
- Both modes are TUI/RPC only. With no UI to ask through, a gated call blocks, the way every `ask` rule degrades. The mode restores from the active session branch, with a visible warning and status indicator, or a stderr diagnostic headlessly. Resuming `/approve-all` under `-p` leaves every gated call unexecuted with an exact-action approval request.
- The gate does **not** reach subagent children. They spawn `--no-session`, so no restored mode state reaches them and they always start with it off — gating the parent's `subagent` call is the only control point over the child's session, which is why it is gated under `/approve-all`.
- `subagent/` spawns children without `--no-extensions`, so each child re-discovers this whole directory and re-pays the load time. It does *not* re-pay the tool-definition tokens: a role's `tools:` frontmatter becomes `--tools`, a strict allowlist across built-in and extension tools alike. The guards still apply to children — one that reads a `.env` is refused and logged to the same `read-access.log`. Children run `--no-session`, so nothing is served from your prompt cache.

Retire installed `protected-paths.ts`, `protected-paths-bash.ts` and the local `plan-mode/` directory when deploying this layout. Copying alone leaves obsolete guards loaded. Preserve unrelated configuration and state and restart Pi.
