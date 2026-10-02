local M = {
    "sindrets/diffview.nvim",
    commit = "4516612fe98ff56ae0415a259ff6361a89419b0a",
    cmd = { "DiffviewOpen", "DiffviewFileHistory" },
    keys = {
        { "<Leader>gd", "<Cmd>DiffviewOpen<CR>", desc = "Diffview: Open" },
        { "<Leader>gh", "<Cmd>DiffviewFileHistory %<CR>", desc = "Diffview: File history" },
        { "<Leader>gH", "<Cmd>DiffviewFileHistory<CR>", desc = "Diffview: Branch history" },
        { "<Leader>gq", "<Cmd>DiffviewClose<CR>", desc = "Diffview: Close" },
    },
    opts = {},
}

return { M }
