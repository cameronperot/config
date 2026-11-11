# Ghostty

The [Ghostty configuration](../dotfiles/.config/ghostty/config.ghostty) targets Linux with Ghostty 1.3.1 or later and deploys to `~/.config/ghostty/config.ghostty`.
It follows the [Kitty configuration](kitty.md), overriding Ghostty defaults only where needed.
Install Ghostty and JetBrainsMonoNL Nerd Font separately; the dotfile installer copies configuration only.
The optional entry in [dotfiles.yaml](../dotfiles.yaml) allows syncing from machines without Ghostty installed.

## Appearance and behavior

The font is JetBrainsMonoNL Nerd Font at 12 points, with a `#282c34` background, `#dddddd` foreground, Kitty's 16 ANSI colors, and 90% background opacity.
Font size and background are omitted because they already match Ghostty's Linux defaults.
The cursor is a nonblinking block that reverses the cell's colors; shell integration is prevented from changing it to a bar at prompts.
Applications can still request a different cursor style.
There is no explicit window padding, leftover space is centered, and inactive panes remain fully bright.
Tabs appear at the bottom, use native styling, and new tabs are appended at the end.
New windows, tabs, and splits use Ghostty's configured/default working directory rather than following the active shell's directory.
Close confirmation is disabled, matching Kitty's `confirm_os_window_close 0`.

Scrollback has a 100,000,000-byte budget per pane, including the visible screen; this is not an exact equivalent of 100,000 lines.
Mouse-wheel scrolling uses a multiplier of five; precision scrolling retains its default multiplier of one.
Terminal applications can write the clipboard but cannot read it.
Selecting text retains Ghostty's Linux primary-selection behavior without automatically replacing the regular clipboard.
Copied text preserves trailing spaces on nonblank lines; Ghostty still trims entirely blank lines.

These defaults and options were checked against the [Ghostty 1.3.1 configuration source](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/config/Config.zig), [palette defaults](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/terminal/color.zig), and [option reference](https://ghostty.org/docs/config/reference).

## Keyboard mappings

All shortcuts below use `Ctrl+Shift` unless specified otherwise.
Copy/paste, tab creation/navigation, and `Shift+Insert` already match Ghostty's Linux defaults and are not repeated in the config.

| Keys | Action |
| :--- | :--- |
| `c` / `v` | Copy / paste the regular clipboard |
| `s` or `Shift+Insert` | Paste the primary selection |
| `Up` / `k`, `Down` / `j` | Scroll one line up / down |
| `u` / `d` | Scroll one page up / down |
| `Home` / `End` | Scroll to the beginning / end |
| `h` | Export plain-text scrollback and open it with the system text-file opener |
| `Enter` | Split the focused pane along its larger dimension |
| `w` | Close the focused pane |
| `[` / `]` | Focus the previous / next pane in creation order |
| `r`, then unmodified arrow keys | Resize the pane in 10-pixel steps; Escape exits |
| `t` / `q` | Create / close a tab |
| `Left` / `Right` | Previous / next tab |
| `,` / `.` | Move the tab backward / forward |
| `Alt+t` | Prompt for a tab title |
| `Equal` / `Plus` / `Keypad+`, `Minus` / `Keypad-` | Increase / decrease font size by two points across all panes and windows |
| `Backspace` | Reset font size across all panes and windows |
| `F11` / `F10` | Toggle fullscreen / maximization |
| `F2` | Open the Ghostty configuration using the system file opener |
| `Delete` | Reset the focused terminal |

Resize mode ignores other keys until Escape; Ghostty shows a key-table indicator while the mode is active.
See the [action reference](https://ghostty.org/docs/config/keybind/reference), [all-surfaces binding prefix](https://ghostty.org/docs/config/keybind#all), and [key-table example](https://ghostty.org/docs/install/release-notes/1-3-0#key-tables-chained-keybinds-and-catch_all).

## Differences from Kitty

| Kitty behavior | Ghostty treatment |
| :--- | :--- |
| `less` scrollback overlay | Opens a plain-text export externally; formatting and pager position are not preserved |
| Firefox URL opener and `Ctrl+Shift`-click | Uses the system browser and `Ctrl`-click |
| Layout cycling, pane reordering, numbered pane selection | No corresponding bindings |
| Hints, Unicode picker, selected-text opener, remote-control shell | No corresponding bindings |
| Opacity shortcut sequences | Omitted; dynamic opacity is disabled in the Kitty config |
| Tab fade, per-state pane borders, pixel-sized initial window, remembered size | Native UI and sizing; Ghostty's state restoration option has no effect on Linux |
| Mouse hiding after three idle seconds, URL underline styling, word-selection rules | Retain Ghostty behavior where there is no exact equivalent |

Conflicting Ghostty bindings on `Ctrl+Shift+A/E/F/N/O/P` are explicitly unbound, including native search and command-palette shortcuts.
Unbound keys can reach terminal applications; unrelated Ghostty shortcuts remain available.
Ghostty keeps its own `TERM=xterm-ghostty`; the Kitty terminal identifier is not copied.
The repository's desktop launchers still start Kitty, and [tmux](tmux.md) retains its separate configuration, including its `xterm-kitty` terminal identifier.

## Validation

From the repository root on a machine with Ghostty installed, run `ghostty +validate-config --config-file=dotfiles/.config/ghostty/config.ghostty`.
Use `ghostty +list-fonts` to confirm the font is available, then check pane resizing, tab movement, font-size shortcuts, and scrollback opening in a running terminal.
The configuration was checked against the 1.3.1 source; runtime and visual validation require a Ghostty installation.
