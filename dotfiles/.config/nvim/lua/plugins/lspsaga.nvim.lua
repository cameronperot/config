local M = {
    "nvimdev/lspsaga.nvim",
    commit = "cf6fc9473bba1d332eda9887855ea29ed9b37701",
    event = "LspAttach",
    dependencies = {
        "nvim-treesitter/nvim-treesitter",
        "nvim-tree/nvim-web-devicons",
    },
    keys = {
        { "K", "<Cmd>Lspsaga hover_doc<CR>", desc = "LSP: Hover doc" },
        { "gd", "<Cmd>Lspsaga goto_definition<CR>", desc = "LSP: Go to definition" },
        { "gD", "<Cmd>Lspsaga peek_definition<CR>", desc = "LSP: Peek definition" },
        { "gt", "<Cmd>Lspsaga goto_type_definition<CR>", desc = "LSP: Go to type definition" },
        { "gT", "<Cmd>Lspsaga peek_type_definition<CR>", desc = "LSP: Peek type definition" },
        { "gr", "<Cmd>Lspsaga finder<CR>", desc = "LSP: Find references" },
        { "<Leader>rn", "<Cmd>Lspsaga rename<CR>", desc = "LSP: Rename" },
        {
            "<Leader>ca",
            "<Cmd>Lspsaga code_action<CR>",
            desc = "LSP: Code action",
            mode = { "n", "v" },
        },
        {
            "<Leader>xd",
            "<Cmd>Lspsaga show_line_diagnostics<CR>",
            desc = "LSP: Line diagnostics",
        },
        { "[d", "<Cmd>Lspsaga diagnostic_jump_prev<CR>", desc = "LSP: Previous diagnostic" },
        { "]d", "<Cmd>Lspsaga diagnostic_jump_next<CR>", desc = "LSP: Next diagnostic" },
    },
    opts = {
        hover = { open_link = {} },
        symbol_in_winbar = { enable = false },
        lightbulb = { enable = false },
    },
}

return { M }
