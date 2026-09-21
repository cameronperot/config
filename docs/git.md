# Git and worktrees

The [Git configuration](../dotfiles/.gitconfig) sets Neovim as the editor, delta as the diff pager, SSH commit signing, merge-based pulls (`pull.rebase=false`), and `gc.worktreePruneExpire=never`. The installer copies it to `~/.gitconfig` without adjusting identity or signing settings.

## Identity, signing, and diffs

The checked-in name and email identify the repository owner, and `user.signingkey` contains the placeholder `(redacted)`. Set the deployed identity and a real signing key before committing. `commit.gpgsign=true` makes signing the default, `gpg.format=ssh` selects SSH signatures, and `gpg.ssh.allowedSignersFile` points to `~/.ssh/allowed_signers`.

See [SSH](ssh.md) for agent selection and forwarding, and the [dev-container signing setup](../dev-container/README.md#commit-signing) for the separate container key and allowed-signers setup.

Delta must be available for both `core.pager=delta` and `interactive.diffFilter=delta --color-only`. Navigation is enabled; `n` / `N` move between diff sections in the pager. Neovim must also be on `PATH` for commit-message editing.

The [global ignore file](../dotfiles/.config/git/ignore) contains `/scratch/`, temporary/backup patterns, language caches, virtual environments, and credential-related filename patterns. Review these patterns if a new file does not appear in Git status; ignore rules do not remove already tracked files. The `change-commits` alias invokes `git filter-branch` to rewrite matching metadata and is not part of the normal commit workflow.

## Converting to the `.bare` layout

[`git-bareify`](../dotfiles/bin/git-bareify), installed as `~/bin/git-bareify`, converts a normal clone in place. Run `git-bareify [path]` from the host; the path defaults to the current directory. `--debug` enables shell tracing, and `-h` shows help. When invoking it as `git bareify`, use `-h`, since Git handles `--help` as a manual-page request.

For a checkout on branch `main`, the resulting layout is:

| Path | Purpose |
| :--- | :--- |
| `<repository>/.bare/` | The original Git directory, configured as bare |
| `<repository>/.git` | A file pointing to `.bare` |
| `<repository>/main/` | The current files in a linked worktree |

The branch name determines the worktree path, including nested directories for names such as `feature/example`. The script moves the existing working files, including ignored files, and retains the repository's branches, remotes, stashes, and reflogs. It rebuilds the worktree index and checks that the result is clean.

## Preconditions and follow-up

The script requires a clean checkout with no staged, modified, or untracked files, a named branch, a plain `.git` directory, and exactly one worktree. It rejects a `.gitmodules` file, `core.worktree`, enabled sparse checkout or worktree-scoped configuration, and paths that would collide with `.bare` or the new worktree directory.

Conversion moves the working directory's contents. Enter the printed worktree path afterward, and recreate virtual environments that embed the previous absolute path. There is no dry-run option or automatic rollback; if conversion fails after mutation begins, inspect the reported stage and filesystem before attempting recovery.

`gc.worktreePruneExpire=never` keeps stale worktree metadata from expiring under the configured default. Review worktrees explicitly when removing old checkouts.

The [agent sandbox](agent-sandbox.md#workspace-and-filesystem-access) treats a Git common directory named `.bare` specially: it exposes the containing directory, including sibling worktrees, as the writable workspace. Ordinary linked worktrees instead expose their shared Git metadata while hiding sibling contents. This layout therefore changes the scope visible to sandboxed agents; perform conversion and worktree management from the host.
