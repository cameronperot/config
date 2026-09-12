# Containers keep the supplied signing socket
if [[ -n "${container:-}" ]]; then
    return 0
fi

if [[ -n "${SSH_CONNECTION:-}" ]]; then
    if [[ -n "${TMUX:-}" ]]; then
        if [[ -z "${XDG_RUNTIME_DIR:-}" || ! -d "${XDG_RUNTIME_DIR}" ]]; then
            echo "zshrc: XDG_RUNTIME_DIR is unavailable; cannot select the forwarded SSH agent link" >&2
        else
            export SSH_AUTH_SOCK="${XDG_RUNTIME_DIR}/ssh-forwarded-agent.sock"
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
