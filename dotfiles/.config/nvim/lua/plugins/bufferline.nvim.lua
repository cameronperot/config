local M = {
    "akinsho/bufferline.nvim",
    commit = "655133c3b4c3e5e05ec549b9f8cc2894ac6f51b3",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    event = "VeryLazy",
    keys = (function()
        local ks = {
            { "[b", "<Cmd>BufferLineCyclePrev<CR>", desc = "BufferLine: Cycle tab left" },
            { "]b", "<Cmd>BufferLineCycleNext<CR>", desc = "BufferLine: Cycle tab right" },
            { "[B", "<Cmd>BufferLineMovePrev<CR>", desc = "BufferLine: Move tab left" },
            { "]B", "<Cmd>BufferLineMoveNext<CR>", desc = "BufferLine: Move tab right" },
        }
        for i = 1, 9 do
            table.insert(ks, {
                string.format("<Leader>%d", i),
                string.format("<Cmd>BufferLineGoToBuffer %d<CR>", i),
                desc = "BufferLine: Go to " .. i,
            })
        end
        return ks
    end)(),
    config = function()
        local bufferline = require("bufferline")
        bufferline.setup({
            options = {
                style_preset = bufferline.style_preset.no_italic,
                numbers = function(opts)
                    return string.format("%s", opts.ordinal)
                end,
                hover = {
                    enabled = true,
                    delay = 200,
                    reveal = { "close" },
                },
                offsets = {
                    {
                        filetype = "neo-tree",
                        separator = false,
                    },
                },
            },
            highlights = {
                fill = { bg = "NONE" },
                background = { bg = "NONE" },
                tab = { bg = "NONE" },
                numbers = { bg = "NONE" },
                close_button = { bg = "NONE" },
                separator = { bg = "NONE" },
                modified = { bg = "NONE" },
                duplicate = { bg = "NONE" },
                indicator_selected = { fg = "#98c379" },
            },
        })
    end,
}

return { M }
