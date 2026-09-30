local M = {
    "nvim-telescope/telescope.nvim",
    version = "0.2.1",
    dependencies = { "nvim-lua/plenary.nvim" },
    keys = {
        {
            "<Leader>ff",
            function()
                require("telescope.builtin").find_files()
            end,
            desc = "Telescope: Find files",
            silent = true,
        },
        {
            "<Leader>fg",
            function()
                require("telescope.builtin").live_grep()
            end,
            desc = "Telescope: Live grep",
            silent = true,
        },
        {
            "<Leader>fb",
            function()
                require("telescope.builtin").buffers()
            end,
            desc = "Telescope: Find buffers",
            silent = true,
        },
        {
            "<Leader>fh",
            function()
                require("telescope.builtin").help_tags()
            end,
            desc = "Telescope: Find help tags",
            silent = true,
        },
        {
            "<Leader>fd",
            function()
                require("telescope.builtin").current_buffer_fuzzy_find()
            end,
            desc = "Telescope: Fuzzy find in current buffer",
            silent = true,
        },
    },
    config = function()
        require("telescope").setup({
            defaults = {
                preview = { check_mime_type = false },
            },
            extensions = {
                fzf = {
                    fuzzy = true,
                    override_generic_sorter = true,
                    override_file_sorter = true,
                    case_mode = "smart_case",
                },
            },
        })
        require("telescope").load_extension("fzf")
    end,
}

return { M }
