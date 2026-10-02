local M = {
    "saghen/blink.cmp",
    commit = "78336bc89ee5365633bcf754d93df01678b5c08f",
    event = "InsertEnter",
    ---@module 'blink.cmp'
    ---@type blink.cmp.Config
    opts = {
        keymap = {
            preset = "none",
            ["<C-p>"] = { "select_prev", "fallback" },
            ["<C-n>"] = { "select_next", "fallback" },
            ["<Tab>"] = { "select_next", "fallback" },
            ["<S-Tab>"] = { "select_prev", "fallback" },
            ["<C-d>"] = {
                function(cmp)
                    return cmp.scroll_documentation_down(8)
                end,
                "fallback",
            },
            ["<C-u>"] = {
                function(cmp)
                    return cmp.scroll_documentation_up(8)
                end,
                "fallback",
            },
            ["<C-Space>"] = { "show", "show_documentation", "hide_documentation" },
            ["<C-e>"] = { "hide", "fallback" },
            ["<CR>"] = { "select_and_accept", "fallback" },
        },
        appearance = {
            nerd_font_variant = "mono",
        },
        completion = {
            accept = {
                auto_brackets = { enabled = false },
            },
            list = {
                selection = { preselect = false, auto_insert = true },
            },
            menu = {
                border = "padded",
                draw = {
                    columns = {
                        { "source_icon" },
                        { "label", "label_description", gap = 1 },
                        { "kind_icon", "kind", gap = 1 },
                    },
                    components = {
                        source_icon = {
                            text = function(ctx)
                                local icons = {
                                    lsp = "λ",
                                    buffer = "Ω",
                                    path = "🖫",
                                }
                                return icons[ctx.source_id] or ctx.source_name
                            end,
                            highlight = "BlinkCmpSource",
                        },
                    },
                },
            },
            documentation = {
                auto_show = true,
                auto_show_delay_ms = 0,
                window = { border = "padded" },
            },
        },
        signature = {
            enabled = true,
            window = { border = "padded" },
        },
        sources = {
            default = { "lsp", "path", "buffer" },
            providers = {
                buffer = { min_keyword_length = 1 },
                lsp = { min_keyword_length = 1 },
            },
        },
        fuzzy = { implementation = "prefer_rust_with_warning" },
    },
    opts_extend = { "sources.default" },
}

return { M }
