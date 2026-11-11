---
name: pi-create-skill
description: Guides authoring Pi agent skills — SKILL.md with trigger-driving frontmatter plus optional scripts/, references/, and assets/, per the Agent Skills spec and house conventions. Use when explicitly asked to create, review, or fix a Pi skill or SKILL.md. Not for prompt templates (pi-create-prompt) or TypeScript extensions (pi-create-extension).
disable-model-invocation: true
---

# pi-create-skill

Author a Pi agent skill that triggers reliably on realistic phrasings and passes the pre-ship checklist clean in one pass.

Trailing input after `/skill:pi-create-skill` describes the skill to create (purpose, trigger contexts) or names an existing skill to review or fix; with no input, derive the requirements from the conversation and ask for anything missing in one consolidated question.

## Confirm the genre

- Reusable prompt text the user expands, reviews, and edits before sending — a one-shot task or checklist with no bundled files — is a prompt template, not a skill: switch to `/skill:pi-create-prompt`.
- Behavior instructions cannot express — new tools, slash commands that execute code, event interception, UI, providers, context injection — is an extension: switch to `/skill:pi-create-extension`.
- Tiebreak for "/name command" requests: a /name that inserts editable prompt text is a template; a /name that executes code or opens UI is an extension command.
- Instructions, multi-step workflows, domain knowledge, bundled scripts, or reference docs the agent loads when a task matches — that is a skill; continue here.

## Gather requirements

Establish before writing:

- Purpose, and the concrete failures the skill fixes: when feasible, run the task without a skill on 2–3 realistic prompts and note what goes wrong — never write a skill restating what the model already does right.
- Realistic trigger phrasings, including ones where the user does not name the skill.
- Trigger tier (see the Description section).
- Bundled files needed: scripts, references, assets — or none.
- Target location: global `~/.pi/agent/skills/`, project `.pi/skills/` (loaded only after the project is trusted), or a package's `skills/` directory.

Ask at most one consolidated question, and only when the tier or location is not inferable.

## Anatomy and discovery

```
my-skill/
├── SKILL.md          # required: YAML frontmatter + markdown instructions
├── scripts/          # helper scripts the agent executes
├── references/       # detailed docs loaded on demand
└── assets/           # templates and data files used in output
```

At startup Pi puts only each skill's name + description into the system prompt; the agent reads the full SKILL.md when a task matches, and references and scripts cost zero context until read or executed.
Discovery locations: `~/.pi/agent/skills/` and `~/.agents/skills/` (global), `.pi/skills/` and `.agents/skills/` in cwd and ancestors (project, after trust), packages (`skills/` dir or `pi.skills` in package.json), the `skills` settings array, and `--skill <path>`.
Discovery is recursive; a directory containing a SKILL.md is a skill root and recursion stops there.
Every skill also registers as `/skill:name`; arguments after the command are appended to the skill content.

## Frontmatter

| Field | Required | Rules |
|---|---|---|
| `name` | Yes | 1–64 chars; lowercase a-z, 0-9, hyphens; no leading/trailing/consecutive hyphens; must match the directory name (the Agent Skills spec requires it, so portability does too) |
| `description` | Yes | Max 1,024 chars; what the skill does and when to use it; a skill with a missing or malformed description is silently not loaded — check startup warnings when a skill "doesn't exist" |
| `license`, `compatibility`, `metadata`, `allowed-tools`, `disable-model-invocation` | No | Optional; use only with a concrete reason |

Stick to spec fields for portability: Pi ignores unknown fields, but claude.ai upload hard-fails on non-spec ones.
Name collisions across locations keep the first skill found and warn — use distinct names.
Do not gate a skill with `disable-model-invocation`; it kills triggering on explicit conversational asks, and the gated lead phrase below is the mechanism instead. Two exceptions: a skill that only a subagent consumes, by reading its SKILL.md directly (py-lint-fix, py-typecheck and py-debug, read by the linter and debugger subagents), and a deliberately command-only skill for a rare, explicitly requested workflow (py-project-init).

## Description

The description is the only thing in context before the agent decides to read the skill, and models under-trigger, so err toward pushy: enumerate the situations that should trigger it.
Every description contains exactly one trigger sentence — the first sentence beginning "Use " — whose tier depends on whether the model could plausibly self-trigger the skill after ordinary work without being asked:

| Tier | Lead phrase | When | Extra sentence |
|---|---|---|---|
| Gated | `Use only when explicitly asked to …` | An ambient trigger path exists — the skill follows naturally after ordinary coding work (commits, changelogs, debugging) | Required: `Do not invoke proactively <ambient scenario>.` |
| Open | `Use when explicitly asked to …` | The request is inherently explicit; no ambient path | — |
| Broad | `Use when asked to …` / `Use whenever <topic> comes up: …` | House-standard tool that should fire even on indirect mentions, or a house-standard step that should fire unprompted after ordinary work (py-test-gen); never contains "explicitly" | — |

Template, in order:

1. Verb-first, third-person what-it-does: 1–3 sentences, concrete capabilities and tool names.
2. The tier trigger sentence, enumerating the asks; quoted literal user phrasings where natural.
3. Gated tier only: the `Do not invoke proactively …` sentence.
4. Where a real sibling collision exists, a final sentence: `Do not use for <adjacent task> (<sibling-skill>).`

Target ≤ ~900 chars (hard cap 1,024); trim mechanism detail (command lists, mode plumbing), never trigger vocabulary (symptom nouns, task phrasings, tool names).
Keep the whole description on one line — never wrap it or split sentences across lines.
YAML scalar form: plain when the text contains no `": "` or `" #"`; double-quoted when it does; `>-` with a single content line only when it needs quoting and also contains double quotes.
Good: `Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents.` — Poor: `Helps with PDFs.`

## Invocation contract

The argument contract lives in the body (the description never mentions arguments), always appears before the first workflow content, and always states a no-input default.

- Form 1 — one-liner, when all input fills one slot (a target, a hint, a symptom): its own paragraph immediately after the H1 intro paragraph, no heading — `` Trailing input after `/skill:<name>` <interpretation>; with no input, <default>. ``
- Form 2 — `## Arguments` as the first H2, when tokens select different behaviors: the lead `` Trailing input after `/skill:<name>` selects the <thing>: ``, a mapping list in precedence order with the catch-all last, `Conversational requests map the same way.` for keyword-shaped token lists, and a closing `With no input, <default>.` line.

Banned phrasings (harness plumbing or legacy drift): "arrives appended as `User: <args>`", "the skill invocation", "Trailing user input", "When invoked as", "If input follows".

## Body craft

- Assume the model is smart; include only what it doesn't know (domain rules, conventions, fragile sequences) — every loaded token competes with the user's actual context.
- Keep SKILL.md focused and well under ~500 lines; push detail into `references/` files linked one level deep, each long reference starting with a table of contents, and give SKILL.md a routing section saying when to read which.
- Imperative form; explain why over ALL-CAPS MUSTs; consistent terminology; one default approach with an escape hatch, not a menu.
- Match freedom to fragility: prose heuristics for open-ended tasks, exact commands ("run exactly this") for fragile sequences.
- For multi-step workflows, give numbered steps and a validation loop (run validator → fix → repeat → only proceed when passing).
- Bundle a script when every invocation would otherwise rewrite the same helper; make execution intent explicit ("Run `./scripts/x.sh`" vs "See `scripts/x.sh` for the algorithm"); scripts handle their own errors with actionable messages and contain no unexplained magic constants.
- If the skill needs dependencies, include a one-time `## Setup` section with explicit install commands — the environment is the user's machine, not a managed sandbox.
- All paths relative to the skill directory, forward slashes only.
- Security: Pi has no sandboxing or permission popups, so instructions run with the agent's full tool access — never include anything a reviewer would find surprising given the description, and never embed credentials (read secrets from environment variables and say so).
- No time-sensitive content; concrete input/output examples for style-sensitive outputs.
- One sentence per physical line; never wrap or split a sentence across lines.

## Skeleton

```markdown
---
name: my-skill
description: <Verb-first, third-person capabilities>. Use when explicitly asked to <enumerated asks>.
---

# my-skill

<One-sentence framing: the standard followed or the non-negotiable outcome.>

Trailing input after `/skill:my-skill` <interpretation>; with no input, <default>.

## Workflow

1. <step>
2. <step>
3. Validate: <check>; fix and repeat until clean.
```

## Validation loop

Run until a full pass is clean; any failure means fix, then restart at 1.

1. Frontmatter lint: name valid and equal to the directory name; description single-line, ≤1,024 chars (target ≤900), third person, exactly one trigger sentence at the right tier, correct scalar form, spec fields only.
2. Body lint: invocation contract before any workflow content with a no-input default; no banned phrasings; relative paths; references one level deep with TOCs; one sentence per line.
3. Load check: from an unrelated directory run `pi --skill <abs-skill-dir> -p "reply ok"` and read the startup output — any validation warning, or the skill missing from the loaded list, fails this step.
4. Trigger test: try 2–3 realistic phrasings that never name the skill and confirm the agent reads SKILL.md unprompted; if not, sharpen the description; confirm `/skill:<name>` works as the fallback.

## Pre-ship checklist

- [ ] `name` valid format and matches the directory name
- [ ] `description` present, third person, single line, right tier, states what + when with trigger terms
- [ ] Only spec frontmatter fields, unless intentionally Pi-only
- [ ] Invocation contract before workflow content, with a no-input default and no banned phrasings
- [ ] All paths relative to the skill directory, forward slashes
- [ ] `## Setup` with explicit install commands if the skill has dependencies
- [ ] References one level deep with TOCs; body stays lean
- [ ] Scripts: execution vs reference intent explicit; errors handled; constants justified
- [ ] Nothing surprising relative to the description; no embedded secrets
- [ ] No startup validation warnings; skill listed and triggers on realistic prompts
