# kitty

The [kitty configuration](../dotfiles/.config/kitty/kitty.conf) deploys to `~/.config/kitty/kitty.conf`. It uses JetBrainsMonoNL Nerd Font at 12 points, a dark background with opacity `0.90`, a nonblinking block cursor, and 100,000 lines of scrollback. Install kitty and the font separately; the dotfile installer only copies the configuration.

## Window and tab bindings

The configured `kitty_mod` is `Ctrl+Shift`. A kitty window is a terminal pane within a tab; [tmux](tmux.md) maintains its own panes and bindings inside that terminal.

| Keys | Action |
| :--- | :--- |
| `Ctrl+Shift+Enter` | Create a window |
| `Ctrl+Shift+w` | Close the window |
| `Ctrl+Shift+[` / `Ctrl+Shift+]` | Previous / next window |
| `Ctrl+Shift+r` | Start resizing windows |
| `Ctrl+Shift+l` | Cycle layouts |
| `Ctrl+Shift+1` through `Ctrl+Shift+9`, then `Ctrl+Shift+0` | Select window 1 through 10 |
| `Ctrl+Shift+t` / `Ctrl+Shift+q` | Create / close a tab |
| `Ctrl+Shift+Left` / `Ctrl+Shift+Right` | Previous / next tab |
| `Ctrl+Shift+,` / `Ctrl+Shift+.` | Move the tab backward / forward |
| `Ctrl+Shift+Alt+t` | Set the tab title |
| `Ctrl+Shift+F11` / `Ctrl+Shift+F10` | Toggle fullscreen / maximization |

All layouts are enabled. The tab bar is at the bottom and appears with at least two tabs. Window size is remembered, and `confirm_os_window_close` is set to `0`.

## Clipboard and scrollback

| Keys | Action |
| :--- | :--- |
| `Ctrl+Shift+c` / `Ctrl+Shift+v` | Copy / paste the clipboard |
| `Ctrl+Shift+s` or `Shift+Insert` | Paste the primary selection |
| `Ctrl+Shift+k` / `Ctrl+Shift+j` | Scroll one line up / down |
| `Ctrl+Shift+u` / `Ctrl+Shift+d` | Scroll one page up / down |
| `Ctrl+Shift+Home` / `Ctrl+Shift+End` | Scroll to the beginning / end |
| `Ctrl+Shift+h` | Open scrollback in the configured `less` pager |

Selecting text does not automatically copy it to the clipboard. `clipboard_control` permits terminal applications to write the clipboard and primary selection, without granting read access. URLs use Firefox as the configured opener.

## Hints and appearance

`Ctrl+Shift+e` starts URL hints. The sequences below start with `Ctrl+Shift+p`; release that chord before pressing the second key.

| Second key | Hint action |
| :--- | :--- |
| `f` | Insert a selected path into the terminal |
| `Shift+f` | Open a selected path |
| `l` / `w` / `h` | Insert a selected line / word / hash |
| `n` | Select a filename and line number |
| `y` | Open a hyperlink |

`Ctrl+Shift+n` opens Unicode input. `Ctrl+Shift+Plus` / `Ctrl+Shift+Minus` change font size by two points, and `Ctrl+Shift+Backspace` restores it. `Ctrl+Shift+F2` opens the configuration for editing.

Dynamic background opacity is disabled even though opacity-changing shortcuts are present. Remote control is disabled and `TERM` is set to `xterm-kitty`. The configuration contains many explicit settings; check kitty's startup diagnostics when using it with a different version. See [dotfile syncing](dotfiles.md) to save local edits.
