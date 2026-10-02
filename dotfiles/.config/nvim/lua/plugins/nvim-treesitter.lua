local M = {
    "nvim-treesitter/nvim-treesitter",
    commit = "e6be2ff65d89df5039cad7a422600757bbf81d02",
    branch = "main",
    lazy = false,
    build = ":TSUpdate",
    config = function()
        require("nvim-treesitter").install({
            "bash",
            "c",
            "cpp",
            "json",
            "julia",
            "lua",
            "python",
            "rust",
            "toml",
            "yaml",
            "markdown",
            "markdown_inline",
        })

        -- Enable treesitter highlighting
        vim.api.nvim_create_autocmd("FileType", {
            pattern = {
                "bash",
                "c",
                "cpp",
                "json",
                "julia",
                "lua",
                "markdown",
                "python",
                "rust",
                "sh",
                "toml",
                "yaml",
            },
            callback = function()
                vim.treesitter.start()
            end,
        })
    end,
}

return { M }
