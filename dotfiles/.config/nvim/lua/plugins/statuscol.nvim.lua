local M = {
    "luukvbaal/statuscol.nvim",
    commit = "887b8a03ea3804628505c9002fd07bd06a3db2e0",
    event = "VeryLazy",
    config = function()
        local builtin = require("statuscol.builtin")
        require("statuscol").setup({
            relculright = true,
            segments = {
                { text = { builtin.foldfunc }, click = "v:lua.ScFa" },
                { text = { "%s" }, click = "v:lua.ScSa" },
                { text = { builtin.lnumfunc, " " }, click = "v:lua.ScLa" },
            },
        })
    end,
}

return { M }
