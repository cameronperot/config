local M = {
    "neovim/nvim-lspconfig",
    commit = "3e8d598d3b5f8338a41699c436e5fa11d2666cf0",
    dependencies = { "saghen/blink.cmp" },
    event = { "BufReadPre", "BufNewFile" },
    -- LSP keybindings handled by lspsaga.nvim
    config = function()
        -- Set capabilities for all servers
        local capabilities = require("blink.cmp").get_lsp_capabilities()
        vim.lsp.config("*", {
            capabilities = capabilities,
        })

        -- Configure servers with specific settings
        -- Suppress Pyright diagnostics (using ruff instead).
        -- Overrides both push (publishDiagnostics) and pull (diagnostic)
        -- handlers so neither delivery mechanism produces diagnostics.
        vim.lsp.config("pyright", {
            settings = {
                python = {
                    pythonPath = vim.g.python3_host_prog,
                },
            },
            handlers = {
                ["textDocument/publishDiagnostics"] = function() end,
                ["textDocument/diagnostic"] = function() end,
            },
        })

        local rust_analyzer = vim.fn.expand("~/.cargo/bin/rust-analyzer")
        if vim.fn.executable(rust_analyzer) ~= 1 then
            rust_analyzer = vim.fn.stdpath("data") .. "/mason/bin/rust-analyzer"
        end
        vim.lsp.config("rust_analyzer", {
            cmd = { rust_analyzer },
            settings = {
                ["rust-analyzer"] = {
                    checkOnSave = {
                        command = "clippy",
                    },
                    cargo = {
                        allFeatures = true,
                    },
                    diagnostics = {
                        enable = true,
                    },
                },
            },
        })
        vim.lsp.enable("rust_analyzer")

        vim.lsp.config("lua_ls", {
            settings = {
                Lua = {
                    diagnostics = {
                        globals = { "vim" },
                    },
                },
            },
        })
    end,
}

return { M }
