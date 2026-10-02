-- Bootstrap Lazy
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
local lazy_commit = "306a05526ada86a7b30af95c5cc81ffba93fef97"
local lazy_url = "https://github.com/folke/lazy.nvim.git"
local function git(args)
    local output = vim.fn.system(vim.list_extend({ "git" }, args))
    if vim.v.shell_error ~= 0 then
        error("lazy.nvim bootstrap failed: git " .. table.concat(args, " ") .. "\n" .. output)
    end
    return vim.trim(output)
end

if not vim.uv.fs_stat(lazypath) then
    git({
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        lazy_url,
        lazypath,
    })
elseif git({ "-C", lazypath, "status", "--porcelain", "--untracked-files=no" }) ~= "" then
    error("lazy.nvim has local changes; resolve them before starting Neovim: " .. lazypath)
end

vim.fn.system({ "git", "-C", lazypath, "cat-file", "-e", lazy_commit .. "^{commit}" })
if vim.v.shell_error ~= 0 then
    git({ "-C", lazypath, "fetch", lazy_url, lazy_commit })
end
git({ "-C", lazypath, "checkout", "--detach", lazy_commit })
if git({ "-C", lazypath, "rev-parse", "HEAD" }) ~= lazy_commit then
    error("lazy.nvim commit verification failed")
end
vim.opt.rtp:prepend(lazypath)

-- Enable Lua module loader cache for performance
vim.loader.enable()

-- Setup Lazy and load plugins
require("lazy").setup({
    { "folke/lazy.nvim", commit = lazy_commit },
    { import = "plugins" },
})

-- Load configurations
require("core.options")
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
