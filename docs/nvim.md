# Neovim

`install.py` downloads the requested Neovim AppImage to `~/bin/nvim` and copies the [Lua configuration](../dotfiles/.config/nvim/) into `~/.config/nvim`. The default release channel is `stable`; pass `--neovim-version none` to skip the download.

[lazy.nvim](https://github.com/folke/lazy.nvim) installs itself and the configured plugins on first launch. Mason installs the configured language servers for Python, Rust, C/C++, JSON, LaTeX, YAML, TOML, and Lua.

## Editor defaults

- Four-space indentation with spaces.
- Relative line numbers, persistent undo, visible whitespace, and smart-case search.
- Treesitter folding with folds open at startup.
- Splits open below and to the right.
- Onedark colors with 24-bit color enabled.
- Trailing whitespace and blank lines at the end of a file are removed on save.
- The Python provider uses `~/.micromamba/envs/dev/bin/python`.

## Key bindings

The leader key is Neovim's default, `\`.

| Keys | Action |
| :--- | :--- |
| `Ctrl+N` | Toggle Neo-tree |
| `Ctrl+H/J/K/L` | Move between windows, including from terminals |
| `<Leader>ff` | Find files |
| `<Leader>fg` | Search project text |
| `<Leader>fb` | Find open buffers |
| `<Leader>fd` | Search the current buffer |
| `<Leader>gg` | Open lazygit |
| `<Leader>bd` | Delete the current buffer |
| `<Leader><Tab>` | Switch to the last buffer |
| `<Leader>y` mappings | Copy text objects to the system clipboard |
| `gs` | Jump with Flash |

Which-key shows the rest of the leader mappings. `:Scratch` opens `~/tmp/scratch.md`.

`init-vscode.lua` loads the core options and keymaps without the Neovim plugin set for VS Code's Neovim integration.
