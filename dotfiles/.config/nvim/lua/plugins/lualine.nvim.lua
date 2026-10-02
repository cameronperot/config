local M = {
    "nvim-lualine/lualine.nvim",
    commit = "221ce6b2d999187044529f49da6554a92f740a96",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    event = "VeryLazy",
    config = function()
        require("lualine").setup({
            options = {
                theme = "onedark",
                icons_enabled = true,
            },
            sections = {
                lualine_a = { "mode" },
                lualine_b = { "branch" },
                lualine_c = { "filename" },
                lualine_x = { "encoding", "fileformat", "filetype" },
                lualine_y = { "progress" },
                lualine_z = { "location" },
            },
        })
    end,
}

return { M }
