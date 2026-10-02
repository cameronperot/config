local M = {
    "danymat/neogen",
    commit = "b2e78708876f4da507839726816010a68e33fec8",
    dependencies = "nvim-treesitter/nvim-treesitter",
    ft = {
        "python",
        "rust",
    },
    cmd = { "Neogen" },
    keys = {
        {
            "<Leader>dg",
            function()
                require("neogen").generate()
            end,
            desc = "Neogen: Generate",
        },
    },
    config = function()
        require("neogen").setup({
            enabled = true,
            input_after_comment = true,
            languages = {
                python = {
                    template = {
                        annotation_convention = "reST",
                    },
                },
            },
        })
    end,
}

return { M }
