# Zsh

[`install.py`](../install.py) installs [`.zshenv`](../dotfiles/.zshenv), [`.zshrc`](../dotfiles/.zshrc), and the [Antidote plugin list](../dotfiles/.zsh_plugins.txt). The first interactive shell clones Antidote into a temporary directory, verifies its pinned commit, installs it without overwriting an existing directory, and builds `~/.zsh_plugins.zsh`. Plugin revisions are pinned in the list.

## Shell behavior

- Vi key bindings with a yellow `+` command-mode indicator.
- A compact prompt with the user, host, current directory, and Git status.
- Session-local history navigation with duplicate cleanup; completed commands are saved immediately with their duration.
- Commands containing `password` or `secret`, in any letter case, are excluded from interactive history and the history file. Leading-space commands are also omitted. These rules do not detect arbitrary credentials or remove previously saved entries.
- Autosuggestions, syntax highlighting, substring history search, fuzzy completion, and extra completions.
- `~/.bash_aliases`, `~/.local_aliases`, and `~/.local_exports` are loaded when present.
- Kitty completions, micromamba, and zoxide are enabled when installed.

## Key bindings

| Keys | Action |
| :--- | :--- |
| `Ctrl+R` | Open ranger, then return to the unchanged command line and cursor |
| `Ctrl+T` | Select files or directories to insert; preview file contents with bat |
| `Alt+C` | Find and enter a directory; preview its contents with lsd |
| `Ctrl+N` | Open Neovim, then return to the unchanged command line and cursor |
| `Ctrl+H` | Search history with fzf; insert the selected command for editing |
| `Tab` | Fuzzy completion with descriptions and filename colors; directory previews for `cd` |
| `<` / `>` in completion | Switch completion groups |
| `Esc`, then `j` / `k` | Search down or up through matching history |

`lt` shows an lsd directory tree. `bat <file>` displays a file with syntax highlighting; Debian's `batcat` is exposed as `bat` when needed. Git uses delta for diffs and interactive staging; press `n` / `N` in the pager to jump between diff sections.

## Activate on an existing host

1. Install `fzf`, `lsd`, `bat`, and `delta` with the host's package manager; delta is commonly packaged as `git-delta`. The dev-container image provisions these tools; rebuild it to obtain bat. Ranger and Neovim are needed for their launcher shortcuts.
2. From this checkout, deploy the shell files with `cp -i dotfiles/{.zshrc,.zshenv,.zsh_plugins.txt,.bash_aliases} "$HOME/"`.
3. Enable delta without replacing existing Git identity or signing settings: run `git config --global core.pager delta`, `git config --global interactive.diffFilter 'delta --color-only'`, and `git config --global delta.navigate true`.
4. Open a new terminal or run `exec zsh`. The changed plugin list regenerates the cached bundle automatically.

SSH agent selection is documented in [SSH](ssh.md).
