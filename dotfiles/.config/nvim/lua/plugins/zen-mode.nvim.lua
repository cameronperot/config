local M = {
    "folke/zen-mode.nvim",
    commit = "8564ce6d29ec7554eb9df578efa882d33b3c23a7",
    cmd = "ZenMode",
    keys = {
        {
            "<Leader>zm",
            "<Cmd>ZenMode<CR>",
            desc = "ZenMode: Toggle",
            noremap = true,
            silent = true,
        },
    },
    opts = {
        window = {
            width = 0.50,
        },
    },
}

return { M }
