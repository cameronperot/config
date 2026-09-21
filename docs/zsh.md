# Zsh

The Zsh configuration provides vi editing, fuzzy completion, history search, and shortcuts for the installed command-line tools.

## Setup and startup files

Install Zsh and Git separately; [`install.py`](../install.py) deploys the configuration but does not install them or change your login shell. See [installation](../README.md#install) for the full dotfile setup. To deploy only the shell files from this checkout, run `cp -i dotfiles/{.zshrc,.zshenv,.zsh_plugins.txt,.bash_aliases} "$HOME/"`, then start a new shell with `exec zsh`.

| File | Purpose |
| :--- | :--- |
| [`.zshenv`](../dotfiles/.zshenv) | Environment for interactive and noninteractive shells: PATH, history location, editors, locale, and tool settings |
| [`.zshrc`](../dotfiles/.zshrc) | Interactive shell: plugins, prompt, history rules, bindings, and integrations |
| [`.zsh_plugins.txt`](../dotfiles/.zsh_plugins.txt) | Antidote plugin list with pinned revisions |
| [`.bash_aliases`](../dotfiles/.bash_aliases) | Shared command aliases, also loaded by Zsh |

`.zshenv` orders existing directories in PATH as `~/bin`, `~/.local/bin`, `~/.cargo/bin`, `~/.juliaup/bin`, inherited PATH, then `~/gems/bin`. The configured editor is `nvim`. Interactive startup loads the [SSH agent hook](ssh.md), then `~/.bash_aliases`, `~/.local_aliases`, and `~/.local_exports` when present; use the last two for host-specific aliases and exports.

## Shell behavior

- Vi editing starts in insert mode. `Esc` enters command mode, shown by a yellow `+`; `i` returns to insert mode.
- The prompt shows user, host, the last two directory components, and Git branch information with `*` for a dirty working tree.
- History uses `~/.zsh_history`, with a limit of 1,000,000 entries. Completed commands are saved with timestamps and duration; other running shells' commands are not imported automatically. Duplicate entries and excess blanks are removed.
- Commands containing `password` or `secret`, in any letter case, are excluded from interactive history and the history file. Leading-space commands are omitted from saved history. These rules do not detect arbitrary credentials or remove previously saved entries.
- Plugins provide autosuggestions, syntax highlighting, substring history search, fuzzy completion, extra completions, Git and DNF aliases, and colored manual pages.

## Key bindings

Shell shortcuts below apply in vi insert mode unless stated otherwise. Fuzzy selection requires `fzf`; file previews additionally require `bat` or `batcat`, and directory previews require `lsd`.

| Keys | Action |
| :--- | :--- |
| `Ctrl+R` | Open ranger, then return to the unchanged command line and cursor |
| `Ctrl+T` | Select files or directories to insert; preview file contents with bat |
| `Alt+C` | Find and enter a directory; preview its contents with lsd |
| `Ctrl+N` | Open Neovim, then return to the unchanged command line and cursor |
| `Ctrl+H` | Search history with fzf; insert the selected command for editing. Falls back to incremental history search if the fzf widget is unavailable |
| `Tab` | Fuzzy completion with descriptions and filename colors; directory previews for `cd` |
| `<` / `>` in completion | Switch completion groups |
| `Esc`, then `j` / `k` | Search down or up through matching history |
| `Right` at the end of the line | Accept the autosuggestion |

Accepting an [autosuggestion](https://github.com/zsh-users/zsh-autosuggestions#usage) fills the command line; press `Enter` to execute it.

## Integrated tools

Install the tools you use with the host's package manager. The [dev-container image](../dev-container/Containerfile) includes `fzf`, `lsd`, `bat`, `git-delta`, and Neovim.

| Tool | Usage in this setup |
| :--- | :--- |
| `lsd` | `l` for a long listing, `la` to include hidden entries, `lt` for a tree |
| `bat` | `bat <file>` for highlighted file contents; `batcat` is aliased to `bat` when needed |
| `ranger` / `nvim` | `Ctrl+R` / `Ctrl+N` launchers require the corresponding executable; `n` also runs Neovim |
| `zoxide` | Initialized when available: `z <name>` jumps to a frequently visited matching directory; `zi <name>` selects interactively using fzf ([usage](https://github.com/ajeetdsouza/zoxide#usage)) |
| `micromamba` | Loads `~/.mamba_init.sh` when present; the [supplied hook](../dotfiles/.mamba_init.sh) activates `dev` if it exists, otherwise `base`. `mm` is an alias |
| `kitty` | Completions are generated and cached when the executable is available |
| `delta` | The [Git configuration](../dotfiles/.gitconfig) enables delta for diffs and interactive staging; this is separate from shell startup |

## Plugins and troubleshooting

The first interactive shell downloads Antidote into `~/.antidote` and plugins into `~/.antidote/cache`, requiring Git and network access. Antidote and plugins are pinned; startup checks Antidote's commit before loading it. The generated `~/.zsh_plugins.zsh` bundle is rebuilt when the plugin list or Antidote script is newer. Edit the plugin list, not the generated bundle, then run `exec zsh`.

If startup reports `plugins unavailable`, the basic shell and local files still load, but plugin features may be missing. Read the preceding error: an incomplete or mismatched `~/.antidote` is deliberately left untouched for inspection. Avoid `antidote update` for routine upgrades because it can move Antidote away from the required commit. Antidote upgrades require updating both the tag and commit in `.zshrc`; plugin upgrades require changing the pins in `.zsh_plugins.txt`.
