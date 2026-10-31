# Micromamba initialization
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${HOME}/.micromamba}"
export MAMBA_EXE="${MAMBA_EXE:-${MAMBA_ROOT_PREFIX}/bin/micromamba}"

__mamba_shell="${ZSH_VERSION:+zsh}"
__mamba_shell="${__mamba_shell:-bash}"
__mamba_setup="$("${MAMBA_EXE}" shell hook --shell "${__mamba_shell}" --root-prefix "${MAMBA_ROOT_PREFIX}" 2>/dev/null)"
if [ $? -eq 0 ]; then
    eval "$__mamba_setup"
else
    alias micromamba="${MAMBA_EXE}"
fi
unset __mamba_setup __mamba_shell

if [ -x "${MAMBA_EXE}" ]; then
    if [ -d "${MAMBA_ROOT_PREFIX}/envs/dev" ]; then
        micromamba activate dev
    else
        micromamba activate base 2>/dev/null
    fi
fi
