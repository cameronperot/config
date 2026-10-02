local M = {
    "m-demare/hlargs.nvim",
    commit = "05f3d1789642d5e1807121c05c42a5e883ba46d3",
    event = { "BufReadPost", "BufNewFile" },
    config = function()
        require("hlargs").setup({})
    end,
}

return { M }
