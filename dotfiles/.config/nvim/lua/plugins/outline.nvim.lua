local M = {
    "hedyhli/outline.nvim",
    commit = "2a132953b944561d45b52e4541ebfff71934a742",
    lazy = true,
    cmd = { "Outline", "OutlineOpen" },
    opts = {
        outline_window = {
            show_numbers = true,
        },
    },
    keys = {
        {
            "<Leader>o",
            "<Cmd>Outline<CR>",
            desc = "Outline: Toggle",
            mode = "n",
            silent = true,
        },
    },
}

return { M }
