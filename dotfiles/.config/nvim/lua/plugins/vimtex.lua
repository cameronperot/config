local M = {
    "lervag/vimtex",
    commit = "16a5609d17a436db7f48046d91747fd6a9d75c74",
    ft = { "tex", "latex" },
    config = function()
        vim.g.vimtex_quickfix_ignore_filters = {
            "Overfull",
            "Underfull",
            "Package hyperref Warning: Token not allowed in a PDF string",
            "contains only floats.",
            '`h" float specifier changed to `ht".',
        }
    end,
}

return { M }
