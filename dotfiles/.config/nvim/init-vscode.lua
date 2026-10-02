-- Enable Lua module loader cache for performance
vim.loader.enable()

-- Load configurations
require("core.options-vscode")
require("core.keymaps")
require("core.commands")
require("core.diagnostics")

-- Fedora installs: sudo dnf install luarocks cmake ctags
-- Debian installs: sudo apt-get install luarocks cmake exuberant-ctags
-- Cargo installs: cargo install stylua tree-sitter-cli
-- Mason installs: MasonInstall codelldb

-- Nerd Fonts
-- https://www.nerdfonts.com/font-downloads
-- https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/JetBrainsMono.zip
