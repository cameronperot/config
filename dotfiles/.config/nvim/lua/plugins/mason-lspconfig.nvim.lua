local M = {
    "williamboman/mason-lspconfig.nvim",
    commit = "b3298993d55fa194279b5eb9dbfb3a43da65cadf",
    dependencies = { "williamboman/mason.nvim" },
    config = function()
        local servers = {
            "pyright@1.1.409",
            "rust_analyzer@2026-04-13",
            "clangd@22.1.0",
            -- "julials",
            "jsonls@4.10.0",
            "texlab@v5.25.1",
            "yamlls@1.22.0",
            "taplo@0.10.0",
            "lua_ls@3.18.2",
        }
        require("mason-lspconfig").setup({
            ensure_installed = servers,
        })

        vim.api.nvim_create_user_command("MasonRestore", function()
            vim.cmd.LspInstall({ args = servers })
        end, { desc = "Reinstall language servers at their pinned versions" })
    end,
}

return { M }
