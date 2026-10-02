local M = {
    "folke/which-key.nvim",
    commit = "3aab2147e74890957785941f0c1ad87d0a44c15a",
    event = "VeryLazy",
    config = function(_, opts)
        local wk = require("which-key")
        wk.setup(opts)
        wk.add({
            { "<Leader>a", group = "ALE/parameter swap" },
            { "<Leader>b", group = "buffer" },
            { "<Leader>c", group = "code" },
            { "<Leader>d", group = "debug/documentation" },
            { "<Leader>f", group = "find/telescope" },
            { "<Leader>g", group = "git/lazygit" },
            { "<Leader>h", group = "hunks/gitsigns" },
            { "<Leader>r", group = "rename/refactor" },
            { "<Leader>t", group = "toggle" },
            { "<Leader>p", group = "python" },
            { "<Leader>u", group = "uv" },
            { "<Leader>n", group = "search" },
            { "<Leader>o", group = "outline" },
            { "<Leader>x", group = "trouble/diagnostics" },
            { "<Leader>y", group = "yank to clipboard" },
            { "<Leader>z", group = "zen" },
            { "g", group = "goto" },
            { "]", group = "next" },
            { "[", group = "previous" },
        })
    end,
}

return { M }
