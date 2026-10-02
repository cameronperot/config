local M = {
    "nvim-telescope/telescope-fzf-native.nvim",
    commit = "b25b749b9db64d375d782094e2b9dce53ad53a40",
    build = "cmake -S. -Bbuild -DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release",
}

return { M }
