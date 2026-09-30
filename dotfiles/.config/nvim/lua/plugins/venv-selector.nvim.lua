local M = {
    "cameronperot/venv-selector.nvim",
    dependencies = {
        "neovim/nvim-lspconfig",
        "nvim-telescope/telescope.nvim",
        "mfussenegger/nvim-dap-python",
    },
    ft = "python",
    keys = {
        { "<Leader>pv", "<cmd>VenvSelect<cr>", desc = "Python: Select venv" },
    },
    opts = {
        options = {
            auto_install_script_dependencies = false,
            picker = "telescope",
            notify_user_on_venv_activation = true,
            on_venv_activate_callback = function()
                require("dap-python").setup(require("venv-selector").python())
            end,
        },
        search = {
            micromamba = {
                command = "fd /bin/python$ ~/.micromamba/envs --full-path --color never -a",
                type = "anaconda",
            },
        },
    },
    config = function(_, opts)
        require("venv-selector").setup(opts)
        local activated = false
        vim.api.nvim_create_autocmd("FileType", {
            pattern = "python",
            callback = function()
                if activated then
                    return
                end
                local venv_python = vim.fn.getcwd() .. "/.venv/bin/python"
                if vim.fn.filereadable(venv_python) == 1 then
                    require("venv-selector").activate_from_path(venv_python)
                    activated = true
                end
            end,
        })
    end,
}

return { M }
