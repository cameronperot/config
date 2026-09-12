# Containers keep the supplied signing socket
if [[ -n "${container:-}" ]]; then
    return 0
fi

if [[ -n "${SSH_CONNECTION:-}" ]]; then
    if [[ -n "${SSH_AUTH_SOCK:-}" ]]; then
        # Existing tmux shells must not restore a socket from an earlier connection
        if [[ -n "${TMUX:-}" || "${SSH_AUTH_SOCK}" == "${HOME}/.ssh/ssh_auth_sock" ]]; then
            export SSH_AUTH_SOCK="${HOME}/.ssh/ssh_auth_sock"
        elif mkdir -p -m 700 "${HOME}/.ssh" && ln -sfn -- "${SSH_AUTH_SOCK}" "${HOME}/.ssh/ssh_auth_sock"; then
            export SSH_AUTH_SOCK="${HOME}/.ssh/ssh_auth_sock"
        else
            echo "zshrc: cannot refresh ${HOME}/.ssh/ssh_auth_sock; keeping the forwarded SSH agent socket" >&2
        fi
    fi
else
    if [[ -z "${XDG_RUNTIME_DIR:-}" || ! -d "${XDG_RUNTIME_DIR}" ]]; then
        unset SSH_AUTH_SOCK
        echo "zshrc: XDG_RUNTIME_DIR is unavailable; cannot select the personal SSH agent" >&2
    elif [[ ! -S "${XDG_RUNTIME_DIR}/ssh-agent.sock" ]]; then
        unset SSH_AUTH_SOCK
        echo "zshrc: ${XDG_RUNTIME_DIR}/ssh-agent.sock is unavailable; cannot select the personal SSH agent" >&2
    else
        export SSH_AUTH_SOCK="${XDG_RUNTIME_DIR}/ssh-agent.sock"
    fi
fi
