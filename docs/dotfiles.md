# Dotfiles

[`install.py`](../install.py) copies the repository's `dotfiles/` tree into `$HOME`. [`sync_dotfiles.py`](../sync_dotfiles.py) works in the other direction, using [`dotfiles.yaml`](../dotfiles.yaml) to select files.

## Syncing

```bash
make update-dotfiles
make update-dotfiles DOTFILES_ARGS=--dry-run
make update-dotfiles DOTFILES_ARGS=--check
uv run sync_dotfiles.py --status
uv run sync_dotfiles.py --discover
uv run sync_dotfiles.py --prune
```

`--dry-run` previews a sync. `--check` reports whether a sync is needed. `--status` reports repository differences without syncing, and `--discover` lists untracked dotfiles covered by the manifest's watch rules.

`--prune` removes orphaned repository files and copies of non-optional entries missing from `$HOME`. Files covered by `allow_orphan` exclusions are kept. Review its output before using it.

The sync never commits or pushes. Pass `--stage` to stage its changes.

| Exit code | Meaning |
| :--- | :--- |
| `0` | Success |
| `1` | Error |
| `2` | Changes found by `--dry-run` or `--check` |

## Manifest

`include` entries are literal paths or fnmatch globs. Directory entries can contain another `include` and `exclude` scope, with paths relative to that directory.

`exclude` entries are regular expressions with search semantics. `optional: true` permits a path or pattern to match nothing. `allow_orphan: true` keeps excluded repository files during pruning.

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

The sync warns about unmatched exclude patterns and untracked files in curated directories. It skips symlinks unless `--follow-symlinks` is set.

Files copied from `$HOME` are checked for private keys, AWS keys, credential assignments, and the expressions in `secret_patterns`. `--strict-secrets` turns those warnings into errors.
