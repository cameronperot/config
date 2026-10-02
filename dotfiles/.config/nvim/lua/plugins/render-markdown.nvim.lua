local M = {
    "MeanderingProgrammer/render-markdown.nvim",
    commit = "640a3ec6d538bad17c328be373c7cad0293d9589",
    ft = { "markdown" },
    dependencies = {
        "nvim-treesitter/nvim-treesitter",
        "nvim-tree/nvim-web-devicons",
    },
    keys = {
        { "<Leader>tm", "<Cmd>RenderMarkdown toggle<CR>", desc = "Toggle render-markdown" },
    },
    opts = {
        enabled = false,
    },
    config = function(_, opts)
        require("render-markdown").setup(opts)
        local function set_hl()
            vim.api.nvim_set_hl(0, "RenderMarkdownH1Bg", { bg = "#2d3343" })
            vim.api.nvim_set_hl(0, "RenderMarkdownH2Bg", { bg = "#2a3335" })
            vim.api.nvim_set_hl(0, "RenderMarkdownH3Bg", { bg = "#2d3335" })
            vim.api.nvim_set_hl(0, "RenderMarkdownH4Bg", { bg = "#2d2d33" })
            vim.api.nvim_set_hl(0, "RenderMarkdownH5Bg", { bg = "#2d2d33" })
            vim.api.nvim_set_hl(0, "RenderMarkdownH6Bg", { bg = "#2d2d33" })
            vim.api.nvim_set_hl(0, "RenderMarkdownCode", { bg = "#2c313a" })
        end
        set_hl()
        vim.api.nvim_create_autocmd("ColorScheme", { callback = set_hl })
    end,
}

return { M }
