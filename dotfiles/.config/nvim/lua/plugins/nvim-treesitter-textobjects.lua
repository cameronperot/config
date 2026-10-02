local M = {
    "nvim-treesitter/nvim-treesitter-textobjects",
    commit = "5c7b0263797dfd1bd6202f2b219f3b53a80b2187",
    branch = "main",
    lazy = false,
    dependencies = { "nvim-treesitter/nvim-treesitter" },
    config = function()
        local select = require("nvim-treesitter-textobjects.select")
        local move = require("nvim-treesitter-textobjects.move")
        local swap = require("nvim-treesitter-textobjects.swap")

        -- Select text objects
        local select_maps = {
            { "af", "@function.outer", "Textobject: Outer function" },
            { "if", "@function.inner", "Textobject: Inner function" },
            { "ac", "@class.outer", "Textobject: Outer class" },
            { "ic", "@class.inner", "Textobject: Inner class" },
            { "ai", "@conditional.outer", "Textobject: Outer conditional" },
            { "ii", "@conditional.inner", "Textobject: Inner conditional" },
            { "al", "@loop.outer", "Textobject: Outer loop" },
            { "il", "@loop.inner", "Textobject: Inner loop" },
            { "aa", "@parameter.outer", "Textobject: Outer parameter" },
            { "ia", "@parameter.inner", "Textobject: Inner parameter" },
            { "a/", "@comment.outer", "Textobject: Comment" },
        }
        for _, m in ipairs(select_maps) do
            vim.keymap.set({ "x", "o" }, m[1], function()
                select.select_textobject(m[2], "textobjects")
            end, { desc = m[3] })
        end

        -- Move to next/previous
        local move_maps = {
            { "]f", "goto_next_start", "@function.outer", "Goto: Next function start" },
            { "]c", "goto_next_start", "@class.outer", "Goto: Next class start" },
            { "]a", "goto_next_start", "@parameter.outer", "Goto: Next parameter start" },
            { "]F", "goto_next_end", "@function.outer", "Goto: Next function end" },
            { "]C", "goto_next_end", "@class.outer", "Goto: Next class end" },
            { "[f", "goto_previous_start", "@function.outer", "Goto: Previous function start" },
            { "[c", "goto_previous_start", "@class.outer", "Goto: Previous class start" },
            {
                "[a",
                "goto_previous_start",
                "@parameter.outer",
                "Goto: Previous parameter start",
            },
            { "[F", "goto_previous_end", "@function.outer", "Goto: Previous function end" },
            { "[C", "goto_previous_end", "@class.outer", "Goto: Previous class end" },
        }
        for _, m in ipairs(move_maps) do
            vim.keymap.set({ "n", "x", "o" }, m[1], function()
                move[m[2]](m[3], "textobjects")
            end, { desc = m[4] })
        end

        -- Swap parameters
        vim.keymap.set("n", "<Leader>as", function()
            swap.swap_next("@parameter.inner")
        end, { desc = "Swap: Next parameter" })
        vim.keymap.set("n", "<Leader>aS", function()
            swap.swap_previous("@parameter.inner")
        end, { desc = "Swap: Previous parameter" })
    end,
}

return { M }
