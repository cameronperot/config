# tmux

The [tmux configuration](../dotfiles/.tmux.conf) uses `Ctrl+Q` as its prefix. Windows and panes start at 1, new splits inherit the current working directory, and destroyed sessions leave the client attached when another session is available.

## Key bindings

Alt bindings work without the prefix.

| Keys | Action |
| :--- | :--- |
| `Alt+h/j/k/l` | Move between panes |
| `Alt+Shift+h/j/k/l` | Swap panes |
| `Alt+Arrow` | Move between panes |
| `Alt+0` through `Alt+9` | Select a window |
| `Alt+[` / `Alt+]` | Select the previous or next window |
| `Alt+{` / `Alt+}` | Move the current window |
| `Alt+Tab` | Select the last window |
| `Alt+v` | Enter copy mode |
| `Alt+b` | Break the current pane into a window |

Prefix bindings use `Ctrl+Q` followed by the listed key.

| Key | Action |
| :--- | :--- |
| `c` | Create a window |
| `h` / `v` | Split horizontally or vertically |
| `H/J/K/L` | Resize the current pane |
| `n` / `p` | Select the next or previous session |
| `s` | Open the session tree |
| `P` | Open a shell popup |
| `T` | Open `~/todo.md` in a Neovim popup |
| `B` | Open btop in a popup |
| `r` | Reload `~/.tmux.conf` |
| `b` | Toggle the status bar |

Copy mode uses vi keys. Press `v` to begin a selection and `y` to copy it.

## Plugins

[TPM](https://github.com/tmux-plugins/tpm) bootstraps itself on first launch. The configured plugins are tmux-resurrect, tmux-fingers, and extrakto. Press `Ctrl+Q`, then `I` to install them.

SSH sessions use a stable agent link so panes keep working after reconnects. See [SSH](ssh.md) for the socket rules.
