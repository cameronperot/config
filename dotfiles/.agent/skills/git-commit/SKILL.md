---
name: git-commit
description: Creates atomic git commits with Conventional Commit messages, splitting unrelated changes. Use only when explicitly asked to commit changes, write a commit message, or modify a commit. Do not invoke proactively after completing a code change.
disable-model-invocation: true
---

# git-commit

Create atomic, well-messaged git commits. Follow the workflow in order; never commit blind.

Trailing input after `/skill:git-commit` constrains the subject, scope, or files. With no input, commit the changes identified in the conversation. If no conversation history is available, default to committing the staged and unstaged changes. When history exists but scope or ownership is unclear, ask before including unrelated work. A request for a commit message authorizes drafting only, not staging or committing.

## Workflow

1. Inspect the current state before anything else: `git status`, `git diff` and `git diff --staged`, then `git log --oneline -10` — context and scope names already in use, nothing more.
2. Partition the changes into logical units: one concern per commit. A bug fix, a feature, and a rename each stand alone. Group at file level. **IF** a single file mixes unrelated concerns **THEN** flag it and ask the user how to proceed rather than attempting hunk-level surgery.
3. Stage the first unit explicitly: `git add <paths>`. Never `git add -A`, `git add .`, or `git commit -a` — blanket staging is how secrets and junk end up in history.
4. Scan the staged diff (`git diff --staged`) before committing:
   - Secrets, tokens, keys, credentials — never commit these; stop and tell the user.
   - Leftover debug output or temporary code.
   - Large or generated files that don't belong in version control.
   - Untracked junk in `git status` → propose `.gitignore` entries instead of committing it.
5. Write the message per the format below.
6. Commit with exactly this form (keeps multi-line messages intact):

   ```bash
   git commit -m "$(cat <<'EOF'
   type(scope): subject

   Body explaining what and why.
   EOF
   )"
   ```

7. Verify: `git log -1 --stat` matches the intended unit; `git status` shows what remains. Repeat steps 2–7 per unit until the tree is clean or only intentionally-uncommitted changes remain.

## Message format (Conventional Commits)

- Header: `type(scope): subject` — imperative mood, lowercase subject, no trailing period, ≤72 characters. Scope is optional; use one already present in `git log` when it fits.
- Types:

  | Type | Use for |
  |---|---|
  | `feat` | New user-facing capability |
  | `fix` | Bug fix |
  | `refactor` | Code change that alters neither behavior nor interface |
  | `perf` | Performance improvement |
  | `docs` | Documentation only |
  | `test` | Adding or fixing tests |
  | `build` | Build system or dependencies |
  | `ci` | CI configuration |
  | `chore` | Maintenance that fits none of the above |

- Body: blank line after the header, wrapped at 72 characters, explains what changed and why — never how; the diff already shows how. Omit the body only when the header says everything.
- Footer: `BREAKING CHANGE: <description>` for breaking changes; issue references (`Closes #123`) when applicable.

Good:

```
fix(gateway): reject bursts above 50 req/s

Prevents the exchange API key from being banned during volatile
markets. The previous limiter counted per-endpoint, so aggregate
traffic could exceed the exchange-wide cap.
```

Bad (vague type-less header, narrates the how, trailing period):

```
Fixed some rate limit stuff in the gateway by adding a counter.
```

## Hooks

- **IF** a pre-commit hook fails **THEN** fix the cause, re-stage, and retry. Never pass `--no-verify` — the hook exists to block exactly this commit.
- **IF** a hook auto-modifies files **THEN** re-stage the modified files and retry once. If it fails again, stop and show the user the hook output.

## Safety rules

- Never amend, rebase, or otherwise rewrite commits that have been pushed.
- Never add AI attribution: no `Co-Authored-By` agent trailers, no "Generated with" lines.
- This skill ends at the commit. Never push unless the user separately asks.
