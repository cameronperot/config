local M = {
    "benomahony/uv.nvim",
    commit = "b0bce1b61584fde99c316aa0587a4996c52df206",
    ft = "python",
    keys = {
        {
            "<Leader>uu",
            function()
                require("uv").pick_uv_commands()
            end,
            desc = "UV: Commands menu",
        },
        {
            "<Leader>ur",
            function()
                require("uv").run_file()
            end,
            desc = "UV: Run file",
        },
        {
            "<Leader>us",
            function()
                require("uv").run_python_selection()
            end,
            desc = "UV: Run selection",
            mode = "v",
        },
        {
            "<Leader>uf",
            function()
                require("uv").run_python_function()
            end,
            desc = "UV: Run function",
        },
        {
            "<Leader>uv",
            function()
                require("uv").pick_uv_venv()
            end,
            desc = "UV: Manage venv",
        },
    },
    opts = {
        keymaps = false,
    },
}

return { M }
