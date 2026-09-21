# Dotfiles

[`install.py`](../install.py) copies the repository's `dotfiles/` tree into `$HOME`. [`sync_dotfiles.py`](../sync_dotfiles.py) works in the other direction, using [`dotfiles.yaml`](../dotfiles.yaml) to select files.

The manifest controls syncing back into the repository, not installation. The installer copies the whole dotfiles tree except `.aider*` entries and can overwrite existing home configuration; see [installation](../README.md#install). Syncing treats `$HOME` as the source of truth and never edits it.

## Requirements

The sync script declares **Python 3.14+** and **PyYAML** in its inline dependency metadata. The commands below use `uv run` to run it with those requirements; install uv first. The `make` shortcuts additionally require Make. Git is needed for the post-sync repository status report and `--stage`.

## Syncing

Run from the repository root. Preview the changes before applying them:

```bash
make update-dotfiles DOTFILES_ARGS=--dry-run
make update-dotfiles
make update-dotfiles DOTFILES_ARGS=--check
uv run sync_dotfiles.py --status
uv run sync_dotfiles.py --discover
uv run sync_dotfiles.py --dry-run --prune
uv run sync_dotfiles.py --prune
```

| Mode | Behavior |
| :--- | :--- |
| No report-only flag | Apply planned copies and deletions to `dotfiles/` |
| `--dry-run` | Print the copy/delete plan without applying it; can be combined with `--prune` |
| `--check` | Report pending changes tersely and signal them through the exit code |
| `--status` | Report pending sync changes, missing entries, and orphaned repository files without syncing; this is not Git status |
| `--discover` | Report home entries outside the manifest's selection, checking top-level dot-entries and children of curated directories |

`--status`, `--check`, and `--discover` are mutually exclusive, and none accepts `--prune`. Use `--dry-run --prune` to preview pruning. `--config PATH` selects another manifest but does not change the source home or destination repository. `--verbose` enables debug logging; `--quiet` restricts output to warnings and errors.

## Copies, deletions, and staging

A normal sync overwrites selected repository files from `$HOME`. For a directory included as a whole, it also **deletes repository files that disappeared from the still-existing source directory, without `--prune`**. For example, with `include: [live]`, removing `~/live/old.txt` while keeping `~/live/` causes the next sync to delete `dotfiles/live/old.txt`.

`--prune` additionally deletes orphaned repository files outside the manifest's selection and repository copies of non-optional entries missing from `$HOME`. Missing optional entries retain their repository copies. Files covered by `allow_orphan` exclusions are also retained. This differs from deleting a child inside a live mirrored directory, which happens during normal syncing.

`--stage` runs `git add dotfiles` after a real sync: it stages **all changes under `dotfiles/`, including pre-existing edits**, not just changes made by that run. It is ignored with a warning in dry-run and report-only modes. The sync never commits or pushes.

## Exit codes

| Exit code | Meaning |
| :--- | :--- |
| `0` | Success |
| `1` | Error |
| `2` | Changes found by `--dry-run` or `--check` |

Default secret skips can still return `0`; success does not mean every selected file was copied. `--status` reports planning errors but does not propagate them to its exit code, including strict-secret findings. For an automated pending-change and secret check, use `--check --strict-secrets`.

## Manifest

`include` entries are literal paths or component-wise fnmatch globs, with `**` for recursive matching. Directory entries can contain another `include` and `exclude` scope, with paths relative to that directory. A directory without a nested include list is selected as a whole, subject to its exclusions; a nested include list selects only the specified children.

`exclude` entries are regular expressions with search semantics. Root exclusions match home-relative paths; nested exclusions match paths relative to their directory, and enclosing exclusions still apply. On an include, `optional: true` permits a missing entry and protects its missing repository copy from pruning. On an exclude, it suppresses warnings when the pattern matches nothing. `allow_orphan: true` on an exclude keeps matching repository files without orphan warnings or pruning, while leaving the home files excluded from syncing.

```yaml
include:
  - .zshrc
  - path: .config
    include:
      - htop
      - path: Code/User
        include: [settings.json, keybindings.json]
exclude:
  - '^\.cache$'
```

The sync warns about unmatched exclude patterns and home entries outside the selection. These are manifest findings, not Git's tracked/untracked status.

Valid source symlinks are skipped by default and their repository copies are retained. `--follow-symlinks` dereferences them into regular file copies rather than preserving links. Broken links are errors; detected directory loops are skipped with a warning. Repository symlinks are not used as copy destinations.

## Secrets and signing-key redaction

Files planned for copying are scanned for private-key blocks, AWS access-key signatures, credential assignments, and the manifest's `secret_patterns` expressions. Unchanged files are not rescanned. By default, a flagged file is skipped with a warning while other changes proceed. `--strict-secrets` aborts the entire sync before any copies, deletions, or staging when a file is flagged.

Unreadable source files are errors and are not copied. Files that cannot be decoded as UTF-8 are treated as binary and bypass the text-signature scan. The scan matches known patterns; it is not a guarantee that a file contains no credentials.

Separately, the sync replaces `signingkey = ...` lines in the repository copy of `.gitconfig` with `signingkey = (redacted)`. The home copy stays unchanged, and comparisons use the redacted content so the key alone does not trigger repeated syncing. Secret scanning still examines the original source content. Redaction is specific to `.gitconfig`; it is not a general credential scrubber. After deploying that repository copy, configure a real signing key as described in [Git and worktrees](git.md).
