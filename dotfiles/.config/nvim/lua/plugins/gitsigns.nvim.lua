local M = {
    "lewis6991/gitsigns.nvim",
    commit = "070a5d7b985546cc57e1fc61e5bc507fecac6045",
    event = { "BufReadPost", "BufNewFile", "FocusGained" },
    keys = {
        {
            "<Leader>hn",
            function()
                require("gitsigns").next_hunk()
            end,
            desc = "Gitsigns: Next hunk",
        },
        {
            "<Leader>hN",
            function()
                require("gitsigns").prev_hunk()
            end,
            desc = "Gitsigns: Previous hunk",
        },
        {
            "<Leader>hs",
            function()
                require("gitsigns").stage_hunk()
            end,
            mode = "n",
            desc = "Gitsigns: Stage hunk",
        },
        {
            "<Leader>hr",
            function()
                require("gitsigns").reset_hunk()
            end,
            desc = "Gitsigns: Reset hunk",
        },
        {
            "<Leader>hs",
            function()
                local gs = require("gitsigns")
                gs.stage_hunk({ vim.fn.line("."), vim.fn.line("v") })
            end,
            desc = "Gitsigns: Stage selected hunk",
            mode = "v",
        },
        {
            "<Leader>hr",
            function()
                local gs = require("gitsigns")
                gs.reset_hunk({ vim.fn.line("."), vim.fn.line("v") })
            end,
            desc = "Gitsigns: Reset selected hunk",
            mode = "v",
        },
        {
            "<Leader>hS",
            function()
                require("gitsigns").stage_buffer()
            end,
            desc = "Gitsigns: Stage buffer",
        },
        {
            "<Leader>hu",
            function()
                require("gitsigns").undo_stage_hunk()
            end,
            desc = "Gitsigns: Undo stage hunk",
        },
        {
            "<Leader>hR",
            function()
                require("gitsigns").reset_buffer()
            end,
            desc = "Gitsigns: Reset buffer",
        },
        {
            "<Leader>hp",
            function()
                require("gitsigns").preview_hunk()
            end,
            desc = "Gitsigns: Preview hunk",
        },
        {
            "<Leader>hb",
            function()
                require("gitsigns").blame_line({ full = true })
            end,
            desc = "Gitsigns: Blame line",
        },
        {
            "<Leader>tb",
            function()
                require("gitsigns").toggle_current_line_blame()
            end,
            desc = "Gitsigns: Toggle line blame",
        },
        {
            "<Leader>hd",
            function()
                require("gitsigns").diffthis()
            end,
            desc = "Gitsigns: Diff this",
        },
        {
            "<Leader>hD",
            function()
                require("gitsigns").diffthis("~")
            end,
            desc = "Gitsigns: Diff against ~",
        },
        {
            "<Leader>td",
            function()
                require("gitsigns").toggle_deleted()
            end,
            desc = "Gitsigns: Toggle deleted",
        },
    },
    config = function()
        require("gitsigns").setup({})
    end,
}

return { M }
