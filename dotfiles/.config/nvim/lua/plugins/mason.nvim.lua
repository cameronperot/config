local M = {
    "williamboman/mason.nvim",
    commit = "2a6940af80375532e5e9e7c1f2fc6319a1b7a69d",
    cmd = { "Mason" },
    config = function()
        require("mason").setup({
            registries = {
                "github:mason-org/mason-registry@2026-10-02-phobic-pull",
            },
            ui = {
                icons = {
                    package_installed = "✓",
                    package_pending = "➜",
                    package_uninstalled = "✗",
                },
            },
        })
    end,
}

return { M }
