# Neovim

The [Lua configuration](../dotfiles/.config/nvim/) combines Telescope and Neo-tree navigation, Treesitter text objects, LSP completion, ALE formatting, Git tools, and Python/Rust debugging. This page describes the checked-in configuration; plugin defaults and requirements can change when plugins are updated.

## Installation and requirements

[`install.py`](../install.py) downloads the requested Neovim AppImage to `~/bin/nvim` and copies the repository's dotfiles, including this configuration, into the home directory. The default release channel is `stable`. `--neovim-version none` skips the Neovim download but still copies dotfiles; `--dry-run` previews the copy. On systems without FUSE, `--extract-appimage` extracts the AppImage and makes `~/bin/nvim` a symlink to the extracted executable. See the [installation instructions](../README.md#install).

Check `nvim --version` and `command -v nvim` to confirm which binary the shell runs. The configuration uses `vim.lsp.config`, introduced in Neovim 0.11, but the unpinned Treesitter `main` branch currently requires **Neovim 0.12+** and **tree-sitter CLI 0.26.1+**. Check the [upstream Treesitter requirements](https://github.com/nvim-treesitter/nvim-treesitter#requirements) when choosing or updating Neovim; the installer's release argument does not validate plugin compatibility.

| Tool | Used for |
| :--- | :--- |
| `rsync`, `wget` | Dotfile installation and the Neovim download respectively |
| Git and network access | Bootstrapping lazy.nvim and downloading plugins |
| C compiler, CMake | Building Telescope's native FZF extension |
| C compiler, `tree-sitter`, `curl`, `tar` | Installing Treesitter parsers |
| `rg` (ripgrep) | Telescope live grep |
| `fd` | Virtual-environment discovery, including the custom micromamba search |
| `lazygit` | The embedded Git UI and log views |
| `uv` | Python commands and ALE's uv integration |
| A working clipboard provider | The explicit `+` register mappings; inspect `:checkhealth vim.provider` |
| A Nerd Font | File icons and other UI glyphs |

Language servers, linters, formatters, and debug adapters have their own runtime requirements. Mason installs the language servers listed below, but there is no automatic installation list for ALE tools or debug adapters. Use `:checkhealth mason` for package-manager requirements and installation problems.

The [micromamba `dev` environment](../environment.yml) includes `pynvim`, `debugpy`, Node.js, Ruff, ty, uv, and tree-sitter CLI. Creating that environment is separate from running `install.py`; see [toolchains](../README.md#toolchains). The Python provider path is fixed at `~/.micromamba/envs/dev/bin/python`, even if micromamba itself is installed elsewhere.

## Configuration layout and loading

| File or directory | Responsibility |
| :--- | :--- |
| [`init.lua`](../dotfiles/.config/nvim/init.lua) | Bootstrap lazy.nvim, import plugin specs, then load core modules |
| [`lua/core/options.lua`](../dotfiles/.config/nvim/lua/core/options.lua) | Editor settings, Python provider, filetype hooks, save cleanup |
| [`lua/core/keymaps.lua`](../dotfiles/.config/nvim/lua/core/keymaps.lua) | Buffers, windows, clipboard, search, and terminal mappings |
| [`lua/core/commands.lua`](../dotfiles/.config/nvim/lua/core/commands.lua) | `:Scratch` |
| [`lua/core/diagnostics.lua`](../dotfiles/.config/nvim/lua/core/diagnostics.lua) | Diagnostic display and cursor-hold float |
| [`lua/plugins/`](../dotfiles/.config/nvim/lua/plugins/) | Plugin declarations, load triggers, options, and mappings |
| [`init-vscode.lua`](../dotfiles/.config/nvim/init-vscode.lua) | Alternate entry point for VS Code |

[lazy.nvim](https://github.com/folke/lazy.nvim) clones itself into Neovim's data directory if absent and installs the declared plugins on first launch. Most UI and editing plugins load on a key, command, filetype, or event. Onedark, Snacks, and the two Treesitter plugins are explicitly loaded at startup. LSP setup can load Blink before its normal `InsertEnter` trigger because Blink is an LSP dependency.

Plugin versions are only partly constrained: Telescope uses `0.2.1`, Blink uses `1.*`, Rustaceanvim uses `^5`, Neo-tree uses `v3.x`, and both Treesitter plugins use `main`. The [sync manifest](../dotfiles.yaml) excludes `lazy-lock.json`, so the repository does not preserve a complete set of plugin revisions across machines.

## Editor defaults

- Four-space indentation with spaces, smart indentation, and a column marker at **88**. The marker does not set formatter line lengths.
- Absolute current-line and relative surrounding line numbers, cursor-line highlighting, an always-visible sign column, and eight lines of scroll margin.
- Persistent undo, visible tabs/trailing spaces, case-insensitive search unless the pattern contains uppercase, and long lines wrapped at word boundaries.
- US English spell checking, disabled in terminal buffers; yanked text is highlighted for 500 ms.
- Treesitter folding with folds initially open. The status column provides clickable folds, signs, and line numbers.
- Splits open below and to the right. Onedark and 24-bit color are enabled; PaperColor and Seoul256 are available as lazy-loaded alternatives.
- Comment continuation is disabled generally. Markdown restores continuation for the configured list and quote markers.
- Every save strips trailing whitespace and blank lines at the end of the file, including files excluded from ALE fixing. This also removes Markdown's two-space hard line breaks.

Diagnostics use signs and underlines, with inline virtual text disabled and no updates while typing in Insert mode. Holding the cursor still opens a non-focusable diagnostic float; `updatetime` is 300 ms. Snacks adds indentation guides, notifications, and underlined LSP symbol references. Lualine shows mode, branch, filename, encoding, file format, filetype, progress, and location.

## Key bindings

The leader key is Neovim's default, **`\`**: `<Leader>ff` means press `\`, then `f`, then `f`. Keys are case-sensitive. Unless a row says otherwise, mappings are for Normal mode. Which-key displays available mappings after a prefix.

### Files, buffers, and windows

| Keys | Action |
| :--- | :--- |
| `Ctrl+N` | Toggle Neo-tree in Normal mode |
| `<Leader>ff` | Find files |
| `<Leader>fg` | Live grep from the current working directory |
| `<Leader>fb` | Find open buffers |
| `<Leader>fh` | Search help tags |
| `<Leader>fd` | Fuzzy search the current buffer |
| `<Leader>bd` / `<Leader>bD` | Delete the current buffer / force deletion, discarding unsaved changes |
| `<Leader>bx` / `<Leader>bX` | Delete all buffers / force deletion, discarding unsaved changes |
| `<Leader><Tab>` | Switch to the last buffer |
| `[b` / `]b` | Cycle to the previous / next buffer in Bufferline |
| `[B` / `]B` | Move the current buffer left / right in Bufferline |
| `<Leader>1` through `<Leader>9` | Select a buffer by its Bufferline ordinal |
| `Ctrl+H/J/K/L` | Move to the left/down/up/right window, including from Terminal mode |
| `Ctrl+Left/Right` | Decrease / increase window width by two columns |
| `Ctrl+Down/Up` | Decrease / increase window height by two lines |
| `Ctrl+\`, then `Ctrl+L` | Send a clear-screen character to the current terminal, from Normal or Terminal mode |
| `<Leader>nh` | Clear search highlighting |
| `<Leader>o` | Toggle the symbol outline |
| `<Leader>zm` | Toggle Zen mode, configured to half the editor width |

Neo-tree opens on the right at width 48, follows the current file, shows dotfiles and Git-ignored entries, groups empty directories, and closes when a file is opened. Inside its window, `h` closes a node and `l` opens it. Bufferline entries are buffers, not Neovim tab pages.

`Ctrl+Q` is disabled in Normal, Visual, Select, and Operator-pending modes.

### Clipboard

These mappings explicitly use the system clipboard register `+`; ordinary `y` is not remapped to it.

| Keys | Copy to clipboard |
| :--- | :--- |
| `<Leader>yy` | Current line |
| `<Leader>yip` | Inner paragraph |
| `<Leader>yaf` / `<Leader>yac` | Outer function / class, using Treesitter text objects |
| `<Leader>yb` | Entire buffer |
| `<Leader>yw` / `<Leader>yW` | Inner word / whitespace-delimited WORD |
| `<Leader>yas` | Sentence |
| `<Leader>yab` | Parenthesized block, including parentheses |
| `<Leader>y$` / `<Leader>y0` | To the end / start of the line |
| `<Leader>y` in Visual mode | Selection |

### Completion and editing

Blink completion uses LSP, path, and buffer sources, with documentation and signature windows. No entry is preselected; moving through candidates inserts a preview. Completion acceptance does not add brackets, while `nvim-autopairs` handles paired characters during typing.

| Keys | Insert-mode completion action |
| :--- | :--- |
| `Ctrl+N` / `Tab` | Next candidate |
| `Ctrl+P` / `Shift+Tab` | Previous candidate |
| `Enter` | Select and accept a candidate, with normal fallback when completion does not handle it |
| `Ctrl+Space` | Show completion or show/hide its documentation |
| `Ctrl+E` | Hide completion |
| `Ctrl+D` / `Ctrl+U` | Scroll completion documentation down / up by eight lines |

Mini.surround maps `ys` to add a surrounding pair using a motion/text object, `ds` to delete a pair, and `cs` to replace one. In Visual mode, `S` surrounds the selection.

Treesitter installs parsers for Bash, C, C++, JSON, Julia, Lua, Python, Rust, TOML, YAML, Markdown, and inline Markdown. Highlighting is enabled for the configured filetypes; parser installation alone does not add an LSP or formatter. Text objects require a parser and matching queries.

| Keys | Treesitter action |
| :--- | :--- |
| `af` / `if` | Outer / inner function |
| `ac` / `ic` | Outer / inner class |
| `ai` / `ii` | Outer / inner conditional |
| `al` / `il` | Outer / inner loop |
| `aa` / `ia` | Outer / inner parameter |
| `a/` | Comment |
| `]f` / `[f`, `]F` / `[F` | Next / previous function start, or end with uppercase `F` |
| `]c` / `[c`, `]C` / `[C` | Next / previous class start, or end with uppercase `C` |
| `]a` / `[a` | Next / previous parameter start |
| `<Leader>as` / `<Leader>aS` | Swap parameter with the next / previous one |

The selection keys work in Visual and Operator-pending modes, for example `vaf` or `dif`. The movement keys work in Normal, Visual, and Operator-pending modes; swaps use Normal mode. hlargs highlights function arguments.

| Keys | Flash action and mode |
| :--- | :--- |
| `gs` | Jump; Normal, Visual, Operator-pending |
| `gS` | Select a Treesitter node; Normal, Visual, Operator-pending |
| `r` | Remote operation; Operator-pending |
| `R` | Treesitter search; Visual, Operator-pending |
| `Ctrl+S` | Toggle Flash during command-line search |

## Language servers, diagnostics, and formatting

[`mason-lspconfig.nvim.lua`](../dotfiles/.config/nvim/lua/plugins/mason-lspconfig.nvim.lua) requests the following servers. [Mason-lspconfig automatically enables Mason-installed servers by default](https://github.com/mason-org/mason-lspconfig.nvim#automatically-enable-installed-servers); the configuration leaves that behavior enabled.

| Language | Server | Local customization |
| :--- | :--- | :--- |
| Python | `pyright` | Provider interpreter as initial Python path; push and pull diagnostic handlers suppressed |
| Rust | `rust_analyzer` | Clippy check-on-save setting, all Cargo features, diagnostics enabled; see the Rust caveat below |
| C/C++ | `clangd` | Server defaults |
| JSON | `jsonls` | Server defaults |
| LaTeX | `texlab` | Server defaults |
| YAML | `yamlls` | Server defaults |
| TOML | `taplo` | Server defaults |
| Lua | `lua_ls` | Recognize `vim` as a global |

Julia has a parser but its Mason server entry is commented out. There is no configured JavaScript/TypeScript language server or parser installation entry.

### LSP and diagnostic mappings

| Keys | Action |
| :--- | :--- |
| `K` | Hover documentation |
| `gd` / `gD` | Go to / peek definition |
| `gt` / `gT` | Go to / peek type definition |
| `gr` | Lspsaga finder; the installed plugin defaults to references and implementations |
| `<Leader>rn` | Rename symbol |
| `<Leader>ca` | Code action; Normal or Visual mode |
| `<Leader>xd` | Show line diagnostics |
| `[d` / `]d` | Previous / next diagnostic |
| `[[` / `]]` | Previous / next highlighted symbol reference through Snacks; Normal or Terminal mode |
| `<Leader>xx` / `<Leader>xX` | Toggle Trouble diagnostics for this buffer / workspace |
| `<Leader>xs` | Toggle document symbols in Trouble |
| `<Leader>xl` | Toggle Trouble's LSP view on the right |
| `<Leader>xL` / `<Leader>xQ` | Toggle location list / quickfix list in Trouble |
| `<Leader>dg` | Generate documentation with Neogen; Python uses reStructuredText annotations |

LSP actions depend on an attached server and its capabilities. Lspsaga disables its lightbulb and symbol winbar. `gt`, `gT`, and `gr` replace their usual Normal-mode meanings.

### ALE linting and fixing

ALE runs the explicitly configured linters and fixes on save. `<Leader>af` runs `:ALEFix` manually. Python diagnostics are intended to come from **Ruff and ty**, while Pyright supplies navigation and completion.

| Filetype | ALE linters | ALE fixers |
| :--- | :--- | :--- |
| `cpp` | `clang` | `clang-format` |
| `lua` | `luacheck` | `stylua` |
| `python` | `ruff`, `ty` | `ruff`, then `ruff_format` |
| `rust` | None configured in ALE | `rustfmt` |
| `sh` | `shellcheck` | `shfmt` |
| `vim` | `vint` | None configured |

The explicit linter/fixer tables have a `cpp` entry but no `c` entry, despite ALE's C filetype load trigger. The C++ clang-format settings use LLVM style, four-space indentation, and a 100-column limit. Ruff's lint/fix integration receives `--line-length=98`; the separate `ruff_format` integration has no line-length override here and uses Ruff's project configuration or default. StyLua uses width 96 and four spaces; shfmt uses four spaces; luacheck uses Lua 5.4 rules and ignores unused arguments. These widths differ from the editor's 88-column marker.

ALE's Python uv options are enabled for Ruff and ty. Paths matching `lsq/ccxt` disable automatic ALE fixing, but manual `:ALEFix` and the core save-time whitespace cleanup still apply. Use `:ALEInfo` to inspect selected executables, configuration, and command output when linting or fixing fails.

## Python environments and running code

The Python provider, project interpreter, and debugger interpreter have separate roles:

- The Neovim Python provider remains `~/.micromamba/envs/dev/bin/python` and needs `pynvim`.
- `<Leader>pv` opens `:VenvSelect` through Telescope. In addition to the selector's default searches, the configuration searches `~/.micromamba/envs` with `fd`.
- On a Python `FileType` event, the custom hook attempts to activate `.venv/bin/python` under Neovim's **current working directory**. After its first successful activation, that hook stops looking for another environment for the rest of the session; use the selector when changing projects.
- Each environment activation reconfigures `dap-python` to run its adapter with the selected Python. That interpreter must have `debugpy`; this is separate from the provider's `pynvim` requirement. See [dap-python's interpreter requirements](https://github.com/mfussenegger/nvim-dap-python#usage).

| Keys | uv.nvim action |
| :--- | :--- |
| `<Leader>uu` | Pick a uv command |
| `<Leader>ur` | Run the current Python file |
| `<Leader>us` | Run the selection; Visual mode |
| `<Leader>uf` | Run the current function |
| `<Leader>uv` | Open uv's environment picker |

## Debugging

[`nvim-dap.lua`](../dotfiles/.config/nvim/lua/plugins/nvim-dap.lua) configures Python and Rust launch entries, DAP UI, and virtual text. Python's `Launch file` runs the current file using the selected environment, falling back to the provider interpreter. Rust's `Launch file` prompts for an executable starting under the current directory's `target/debug/`; build the executable first. CodeLLDB must be available as `codelldb`; `:MasonInstall codelldb` is the manual installation noted in `init.lua`.

| Keys | Debug action |
| :--- | :--- |
| `<Leader>dc` | Start / continue |
| `<Leader>dp` | Run the last configuration |
| `<Leader>dh` | Run to cursor |
| `<Leader>dj` / `<Leader>dk` / `<Leader>dl` | Step into / out / over |
| `<Leader>db` / `<Leader>dB` | Toggle breakpoint / set a conditional breakpoint |
| `<Leader>dx` | Clear all breakpoints |
| `<Leader>dw` | Add the current expression to watches |
| `<Leader>dW` | Remove the last watch; the mapping passes no watch index |
| `<Leader>dt` | Toggle the debug UI |
| `<Leader>dq` | Terminate the session |

The UI opens when debugging initializes and closes on termination or exit. Scopes, breakpoints, stacks, and watches appear on the left; REPL and console appear below.

Rustaceanvim adds `<Leader>rh` for hover actions and `<Leader>ra` for Rust code actions, scoped to Rust files. **The Rust LSP configuration overlaps:** Mason's automatic enablement includes `rust_analyzer`, and Rustaceanvim also starts a Rust client. This can attach two clients to the same file, with separate settings. [Rustaceanvim advises against also setting up rust-analyzer separately](https://github.com/mrcjkb/rustaceanvim#quick-setup). Resolve which integration owns the server before relying on a single set of diagnostics or actions.

## Git

| Keys | Action |
| :--- | :--- |
| `<Leader>gg` | Open lazygit |
| `<Leader>gf` / `<Leader>gl` | Open lazygit's file log / repository log |
| `<Leader>gd` | Open Diffview |
| `<Leader>gh` / `<Leader>gH` | Diffview history for the current file / branch |
| `<Leader>gq` | Close Diffview |
| `<Leader>hn` / `<Leader>hN` | Next / previous Git hunk |
| `<Leader>hs` / `<Leader>hr` | Stage / reset hunk; selected lines in Visual mode |
| `<Leader>hS` / `<Leader>hR` | Stage / reset the whole buffer |
| `<Leader>hu` | Undo staging the hunk |
| `<Leader>hp` | Preview hunk |
| `<Leader>hb` | Show full blame for the current line |
| `<Leader>tb` | Toggle current-line blame |
| `<Leader>hd` / `<Leader>hD` | Diff against the index / `~` (the previous commit) |
| `<Leader>td` | Toggle deleted-line display |

Resetting a hunk or buffer discards its unstaged changes. Fugitive provides `:Git` / `:G`; Rhubarb supplies GitHub integration for Fugitive's `:GBrowse` command. The Rhubarb lazy-load trigger is spelled `Gbrowse` in the spec, which does not match `GBrowse`. With the installed plugins, invoking that trigger reports that `Gbrowse` was not found after loading Rhubarb. Load Fugitive and Rhubarb through `:Lazy` before using `:GBrowse` until the trigger is corrected.

## Writing and other commands

| Command or keys | Behavior |
| :--- | :--- |
| `:Scratch` | Create `~/tmp` if necessary and open `~/tmp/scratch.md`; this is a regular persistent file |
| `<Leader>tm` | Toggle in-buffer Markdown rendering, initially disabled |
| `:Tabularize` | Align text using Tabular |
| `:GrammarousCheck` / `:GrammarousReset` | Run / clear Grammarous checks; its external LanguageTool requirements are separate |
| `:Neogen` | Generate documentation for the current construct |

VimTeX loads for TeX/LaTeX files, with selected overfull/underfull, hyperref, and float messages filtered from its quickfix output. A TeX toolchain and viewer are separate requirements; this configuration does not install them.

[`markdown-preview.nvim.lua`](../dotfiles/.config/nvim/lua/plugins/markdown-preview.nvim.lua) declares a browser-preview spec but returns `{}`, so **browser Markdown preview is not enabled**. Its Firefox and Yarn settings have no effect. The active Markdown feature is the toggleable in-buffer renderer.

## VS Code

[`init-vscode.lua`](../dotfiles/.config/nvim/init-vscode.lua) bootstraps lazy.nvim if absent, but its plugin setup call is commented out. It loads `core.options-vscode`, the shared core keymaps, `:Scratch`, and diagnostic settings. The VS Code options use a **98-column** marker and do not apply Onedark; they retain the Python provider path and save-time whitespace cleanup.

This entry point does not supply plugin mappings, completion, text objects, or language servers. Shared clipboard mappings for functions/classes still refer to Treesitter text objects, so those need separate support in the host setup. The [checked-in VS Code settings](../dotfiles/.config/Code/User/settings.json) point to `/home/user/bin/nvim` and `/home/user/.config/nvim/init-vscode.lua`; adjust both paths for the actual account. `install.py` does not rewrite those settings.

## Maintenance and troubleshooting

| Command or check | Purpose |
| :--- | :--- |
| `:Lazy` | Inspect plugin load state, installation/build errors, and updates |
| `:Mason` | Inspect installed language servers and manually install tools |
| `:checkhealth` | Check editor and plugin dependencies |
| `:checkhealth vim.lsp` | Inspect LSP configuration and attached clients |
| `:checkhealth vim.provider` | Check Python and clipboard providers |
| `:ALEInfo` | Diagnose missing linters/formatters and inspect their output |
| `:TSUpdate` | Update installed parsers; also configured as Treesitter's build hook |
| `:messages` | Read startup and runtime errors |
| `:verbose nmap <Leader>ff` | Inspect a mapping and where it was defined |

If first-launch highlighting fails, allow parser installation to finish, inspect build errors, then reopen the buffer. If Python navigation works but diagnostics are absent, check Ruff and ty through `:ALEInfo`: Pyright diagnostics are intentionally suppressed. If Python debugging cannot import `debugpy`, check the interpreter chosen by the environment selector, not just the provider environment.

Repeated environment activation calls `dap-python.setup()` again; the installed plugin's setup appends default launch entries, so the debug configuration picker can accumulate duplicates during a session. Also, `<Leader>dW` removes the last watch rather than the watch under the cursor; use the Watches pane's removal action to choose a specific entry.

[`stylua.sh`](../dotfiles/.config/nvim/stylua.sh) formats the **deployed** `~/.config/nvim` tree, regardless of the shell's current directory. It overwrites and then deletes `~/.config/nvim/stylua.toml`; preserve any existing file before using it. For bringing intentional local configuration changes back into this repository, follow the [dotfile sync workflow](dotfiles.md).
