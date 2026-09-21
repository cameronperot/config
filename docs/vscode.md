# VS Code

The checked-in [settings](../dotfiles/.config/Code/User/settings.json) and [key bindings](../dotfiles/.config/Code/User/keybindings.json) deploy to `~/.config/Code/User/`. They use JSON with comments and configure Neovim integration, Python/Ruff, Jupyter notebooks, Julia, and terminal profiles. `install.py` copies these files but does not install VS Code extensions or rewrite the account-specific paths.

## Setup

Install the extensions corresponding to the features you use. Explicit extension identifiers in the settings include `asvetliakov.vscode-neovim` and `charliermarsh.ruff`; the configuration also contains Python, Jupyter, Julia, spelling, docstring, and Markdown-preview preferences. The theme is One Dark Pro Darker and the editor font is JetBrainsMono Nerd Font.

Review these values before using the configuration on another account:

| Setting | Checked-in value |
| :--- | :--- |
| `vscode-neovim.neovimExecutablePaths.linux` | `/home/user/bin/nvim` |
| `vscode-neovim.neovimInitVimPaths.linux` | `/home/user/.config/nvim/init-vscode.lua` |
| `python.condaPath` | `/home/user/.micromamba/bin/micromamba` |
| `python.defaultInterpreterPath` | `/home/user/.micromamba/envs/dev` |
| `docker.environment.HOST` and `containers.environment.HOST` | `unix:///run/user/1000/podman/podman.sock` |

The file also contains `vim.*` preferences, including `vim.neovimPath=/usr/bin/nvim`. These are separate from the `vscode-neovim.*` configuration; review which Vim integration is installed instead of assuming the two path settings are interchangeable.

## Editor and Neovim behavior

The VS Code settings enable relative line numbers, a 98-column ruler, word wrapping, and formatting on save. The [Neovim entry point](../dotfiles/.config/nvim/init-vscode.lua) bootstraps lazy.nvim but leaves plugin setup disabled. It loads the VS Code core options, shared keymaps, commands, and diagnostic settings. See [Neovim's VS Code notes](nvim.md#vs-code) for the shared mappings and their limitations.

The Neovim options also apply save-time whitespace cleanup and select `~/.micromamba/envs/dev/bin/python` as the Python provider. `Ctrl+Shift+/` invokes the VS Code Neovim restart command.

## Python and notebooks

Ruff is selected as the Python formatter. Python saves request import organization; notebook saves request Ruff import organization and fixes, with notebook formatting enabled. The code-action settings use `explicit`. The settings also carry Flake8/Pylint line-length arguments, so review installed extensions when diagnosing overlapping lint behavior.

Python terminal environment activation is disabled. Jupyter excludes `/usr/bin/python3` from the configured environment list, uses a separate interactive window per file, shows notebook line numbers, and limits text output to 100 lines.

Most notebook letter bindings require focus on the notebook or cell list and no text input focus. They are key sequences, not simultaneous chords.

| Keys | Action |
| :--- | :--- |
| `j` / `k` | Move down / up in focused lists |
| `g g` / `Shift+g` | First / last item in focused lists |
| `a` / `b` | Insert a code cell above / below |
| `y y` / `p p` | Copy / paste a cell |
| `Shift+p Shift+p` | Paste above |
| `d d` | Cut a cell |
| `z z` / `r r` | Undo / redo |
| `y c` | Change a Markdown cell to code |
| `Ctrl+Enter` | Execute the cell and focus its container |
| `Ctrl+Shift+9` / `Ctrl+Shift+0` | Interrupt / restart the Jupyter kernel |

## Terminal and other settings

The integrated terminal defaults to Zsh, with Bash, Fish, and tmux profiles also defined. `terminal.integrated.inheritEnv` is false; compare the terminal's environment with the launching shell when tools or credentials are missing. The external terminal is kitty, and the Julia interrupt command is included in `commandsToSkipShell`.

Git commit signing is enabled; the Git identity and signing key come from [Git configuration](git.md). VS Code telemetry and Julia telemetry/crash reporting are disabled in the settings. The workspace preference sets `security.workspace.trust.untrustedFiles` to `open`.

For configuration changes made through VS Code, follow [dotfile syncing](dotfiles.md). The manifest tracks these two files and excludes runtime state such as history, storage, and profiles.
