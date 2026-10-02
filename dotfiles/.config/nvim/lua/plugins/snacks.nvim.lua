local M = {
    "folke/snacks.nvim",
    commit = "882c996cf28183f4d63640de0b4c02ec886d01f2",
    lazy = false,
    priority = 1000,
    ---@type snacks.Config
    opts = {
        indent = {
            enabled = true,
            indent = { hl = "IndentGuide" },
            scope = { hl = "IndentGuideScope" },
        },
        notifier = { enabled = true },
        lazygit = { enabled = true },
        words = { enabled = true, debounce = 50 },
    },
    config = function(_, opts)
        require("snacks").setup(opts)
        local function set_word_hl()
            vim.api.nvim_set_hl(0, "LspReferenceText", { underline = true })
            vim.api.nvim_set_hl(0, "LspReferenceRead", { underline = true })
            vim.api.nvim_set_hl(0, "LspReferenceWrite", { underline = true })
            vim.api.nvim_set_hl(0, "IndentGuide", { fg = "#2c313a" })
            vim.api.nvim_set_hl(0, "IndentGuideScope", { fg = "#4b5263" })
        end
        set_word_hl()
        vim.api.nvim_create_autocmd("ColorScheme", { callback = set_word_hl })
    end,
    keys = {
        {
            "<Leader>gg",
            function()
                Snacks.lazygit()
            end,
            desc = "LazyGit",
        },
        {
            "<Leader>gf",
            function()
                Snacks.lazygit.log_file()
            end,
            desc = "LazyGit: File log",
        },
        {
            "<Leader>gl",
            function()
                Snacks.lazygit.log()
            end,
            desc = "LazyGit: Log",
        },
        {
            "]]",
            function()
                Snacks.words.jump(1)
            end,
            desc = "Next reference",
            mode = { "n", "t" },
        },
        {
            "[[",
            function()
                Snacks.words.jump(-1)
            end,
            desc = "Previous reference",
            mode = { "n", "t" },
        },
    },
}

return { M }
