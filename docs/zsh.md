# Zsh

[`install.py`](../install.py) installs [`.zshenv`](../dotfiles/.zshenv), [`.zshrc`](../dotfiles/.zshrc), and the [Antidote plugin list](../dotfiles/.zsh_plugins.txt). The first interactive shell clones the pinned Antidote release and builds `~/.zsh_plugins.zsh`. Plugin revisions are pinned in the list.

## Shell behavior

- Vi key bindings with a yellow `+` command-mode indicator.
- A compact prompt with the user, host, current directory, and Git status.
- Local history with duplicate cleanup and password or secret commands excluded.
- Autosuggestions, syntax highlighting, substring history search, fuzzy completion, and extra completions.
- `~/.bash_aliases`, `~/.local_aliases`, and `~/.local_exports` are loaded when present.
- Kitty completions, micromamba, and zoxide are enabled when installed.

## Key bindings

| Keys | Action |
| :--- | :--- |
| `Ctrl+R` | Open ranger |
| `Ctrl+N` | Open Neovim |
| `Ctrl+H` or `hh` | Open hstr |
| `Esc`, then `j` / `k` | Search down or up through matching history |

SSH agent selection is documented in [SSH](ssh.md).
