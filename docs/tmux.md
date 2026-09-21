# tmux

The [tmux configuration](../dotfiles/.tmux.conf) uses `Ctrl+Q` as its prefix: press it, release it, then press the command key. `Ctrl+B` is unbound. Sessions contain windows, which contain panes; detaching leaves their programs running.

## Setup and sessions

Install tmux and Git separately. The configured popups need tmux 3.2 or later; Neovim and btop are required for their respective popups. The [dotfile installer](../README.md#install) deploys `~/.tmux.conf`, or copy just this file from the checkout with `cp -i dotfiles/.tmux.conf "$HOME/"`. Reload a running server with `tmux source-file ~/.tmux.conf`.

| Command | Action |
| :--- | :--- |
| `tmux new -s work` | Create and attach to a session named `work` |
| `tmux ls` | List sessions |
| `tmux attach -t work` | Attach to `work` |
| `tmux new -A -s work` | Attach to `work`, creating it if absent |
| `tmux attach` or the Zsh alias `ta` | Attach to an existing session |

Windows and panes start at 1. New windows and splits inherit the active pane's working directory, and window names follow its directory name. Scrollback holds up to 250,000 lines per pane. Closing a session switches the client to another session when one is available.

## Key bindings

Alt bindings work without the prefix and take precedence over bindings in applications inside tmux.

| Keys | Action |
| :--- | :--- |
| `Alt+h/j/k/l` | Move between panes |
| `Alt+Shift+h/j/k/l` | Swap panes |
| `Alt+Arrow` | Move between panes |
| `Alt+1` through `Alt+9`, `Alt+0` | Select the matching window number; `0` means window 0, not 10 |
| `Alt+[` / `Alt+]` | Select the previous or next window |
| `Alt+{` / `Alt+}` | Swap the current window with the previous or next window and follow it |
| `Alt+Tab` | Select the last window |
| `Alt+Shift+Tab` | Select the last session |
| `Alt+v` | Enter copy mode |
| `Alt+b` | Break the current pane into a window |

Prefix bindings use `Ctrl+Q` followed by the listed key.

| Key | Action |
| :--- | :--- |
| `c` | Create a window |
| `h` / `v` | Split into side-by-side / stacked panes |
| `H/J/K/L` | Resize left / down / up / right by five cells; tmux-fingers can override `J` (see below) |
| `n` / `p` | Select the next or previous session |
| `s` | Open the session tree |
| `P` | Open a shell popup |
| `T` | Open `~/todo.md` in a Neovim popup |
| `B` | Open btop in a popup |
| `r` | Reload `~/.tmux.conf` |
| `b` | Toggle the status bar |
| `Ctrl+Q` | Send the prefix through to the pane, for example to nested tmux |

Useful [default tmux bindings](https://github.com/tmux/tmux/wiki/Getting-Started) also use the configured prefix:

| Key | Action |
| :--- | :--- |
| `d` | Detach, keeping the session running |
| `z` | Toggle pane zoom |
| `,` / `$` | Rename the window / session |
| `x` / `&` | Close the pane / window after confirmation |
| `]` | Paste the most recent tmux buffer |
| `:` | Open the tmux command prompt |
| `?` | List active key bindings, including plugin overrides |

## Copy and clipboard

Press `Alt+v` to enter copy mode, navigate with vi keys, press `v` to begin a selection, then `y` to copy and leave copy mode. `q` exits without copying. Paste with `Ctrl+Q`, then `]`.

`set-clipboard on` enables terminal clipboard integration; extrakto also uses tmux's OSC 52 clipboard support. Copying to the desktop clipboard depends on the outer terminal permitting it; see [tmux's clipboard guide](https://github.com/tmux/tmux/wiki/Clipboard). The configuration sets the terminal inside tmux to `xterm-kitty`, so that terminfo entry must exist on hosts where applications use it. Check with `infocmp xterm-kitty` if applications report an unknown terminal.

## Plugins

[TPM](https://github.com/tmux-plugins/tpm) clones itself into `~/.tmux/plugins/tpm` when missing and attempts plugin installation. Once tmux starts, press `Ctrl+Q`, then uppercase `I` to install any missing plugins and load them. `Ctrl+Q`, then uppercase `U` opens plugin updates. Downloads require network access; these plugin revisions are not pinned.

| Plugin | Keys after `Ctrl+Q` | Usage |
| :--- | :--- | :--- |
| [tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) | `Ctrl+S` / `Ctrl+R` | Save / restore sessions, layouts, directories, and supported programs |
| [tmux-fingers](https://github.com/Morantron/tmux-fingers) | `F` | Show letter hints for paths, hashes, and other text; type a hint to copy, or hold Shift while selecting to copy and paste |
| [extrakto](https://github.com/laktak/extrakto) | `Tab` | Fuzzy-search pane output; `Tab` inserts the selection, `Enter` copies it, and `Ctrl+F` changes the filter |

Resurrect saves and restores only when requested; it does not preserve arbitrary process state. Extrakto requires `fzf` and Python 3. Tmux-fingers may open an installation wizard to obtain its executable. Its upstream default also binds prefix + `J` to jump mode, overriding this configuration's resize-down binding when loaded; use prefix + `:`, then `resize-pane -D 5` to resize down explicitly.

SSH sessions use a stable agent link so panes keep working after reconnects. See [SSH](ssh.md) for the socket rules.
