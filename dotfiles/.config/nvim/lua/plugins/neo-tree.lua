local M = {
    "nvim-neo-tree/neo-tree.nvim",
    commit = "1a14083046d96e88e361d1da00761c40d45012f3",
    branch = "v3.x",
    dependencies = {
        "nvim-lua/plenary.nvim",
        "nvim-tree/nvim-web-devicons",
        "MunifTanjim/nui.nvim",
    },
    cmd = { "Neotree" },
    keys = {
        {
            "<C-n>",
            "<Cmd>Neotree toggle<CR>",
            desc = "Neo-tree: Toggle",
            noremap = true,
            silent = true,
        },
    },
    config = function()
        require("neo-tree").setup({
            close_if_last_window = true,
            window = {
                width = 48,
                position = "right",
                mappings = {
                    ["h"] = "close_node",
                    ["l"] = "open",
                },
            },
            filesystem = {
                follow_current_file = {
                    enabled = true,
                },
                filtered_items = {
                    visible = true,
                    hide_dotfiles = false,
                    hide_gitignored = false,
                },
                group_empty_dirs = true,
            },
            event_handlers = {
                {
                    event = "file_opened",
                    handler = function()
                        require("neo-tree.command").execute({ action = "close" })
                    end,
                },
                {
                    event = "neo_tree_buffer_enter",
                    handler = function()
                        vim.opt_local.number = true
                        vim.opt_local.relativenumber = true
                    end,
                },
            },
        })
    end,
}

return { M }
