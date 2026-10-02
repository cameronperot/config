local M = {
    "windwp/nvim-autopairs",
    commit = "430522f95fe4fb7c511ec64f8c1a90cc6a66c05c",
    event = "InsertEnter",
    config = function()
        require("nvim-autopairs").setup({})
    end,
}

return { M }
