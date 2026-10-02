local M = {
    "folke/flash.nvim",
    commit = "5f0f270fdc7c5b0c21d903ee85b9cb06f2ac636a",
    event = "VeryLazy",
    ---@type Flash.Config
    opts = {},
    keys = {
        {
            "gs",
            mode = { "n", "x", "o" },
            function()
                require("flash").jump()
            end,
            desc = "Flash",
        },
        {
            "gS",
            mode = { "n", "x", "o" },
            function()
                require("flash").treesitter()
            end,
            desc = "Flash: Treesitter",
        },
        {
            "r",
            mode = "o",
            function()
                require("flash").remote()
            end,
            desc = "Flash: Remote",
        },
        {
            "R",
            mode = { "o", "x" },
            function()
                require("flash").treesitter_search()
            end,
            desc = "Flash: Treesitter Search",
        },
        {
            "<C-s>",
            mode = { "c" },
            function()
                require("flash").toggle()
            end,
            desc = "Flash: Toggle search",
        },
    },
}

return { M }
