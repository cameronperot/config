local M = {
    "folke/trouble.nvim",
    commit = "bd67efe408d4816e25e8491cc5ad4088e708a69a",
    cmd = { "Trouble", "TroubleToggle" },
    dependencies = { "nvim-tree/nvim-web-devicons" },
    keys = {
        {
            "<Leader>xX",
            "<Cmd>Trouble diagnostics toggle<CR>",
            desc = "Trouble: Toggle workspace diagnostics",
            noremap = true,
            silent = true,
        },
        {
            "<Leader>xx",
            "<Cmd>Trouble diagnostics toggle filter.buf=0<CR>",
            desc = "Trouble: Toggle buffer diagnostics",
            noremap = true,
            silent = true,
        },
        {
            "<Leader>xs",
            "<Cmd>Trouble symbols toggle focus=false<CR>",
            desc = "Trouble: Toggle document symbols",
            noremap = true,
            silent = true,
        },
        {
            "<Leader>xl",
            "<Cmd>Trouble lsp toggle focus=false win.position=right<CR>",
            desc = "Trouble: Toggle LSP references",
            noremap = true,
            silent = true,
        },
        {
            "<Leader>xL",
            "<Cmd>Trouble loclist toggle<CR>",
            desc = "Trouble: Toggle location list",
            noremap = true,
            silent = true,
        },
        {
            "<Leader>xQ",
            "<Cmd>Trouble qflist toggle<CR>",
            desc = "Trouble: Toggle quickfix list",
            noremap = true,
            silent = true,
        },
    },
    config = function()
        require("trouble").setup({})
    end,
}

return { M }
