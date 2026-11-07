#!/usr/bin/env bash
#
# entrypoint.sh — image entrypoint for dev:latest.
#
# Under crun the OCI process.user is already applied and the command is exec'd
# unchanged. Under krun, the guest applies process.user before this script, so
# `c -k` starts it as guest root and passes the invoker's IDs in DEV_UID and
# DEV_GID. As root it closes the TIOCSTI escape that agent-sandbox refuses to
# run with and bridges the TCP signer, since virtio-fs cannot pass the host
# ssh-agent socket through, then drops to that user. Any failure before the drop
# aborts the launch rather than running the workload uninitialized.

set -euo pipefail

if [[ -e /.krun_config.json ]]; then
    fail() {
        echo "entrypoint: $*" >&2
        exit 1
    }
    [[ "$(id -u)" -eq 0 ]] || fail "krun guest started as uid $(id -u), not root; launch it with c -k"
    [[ "${DEV_UID:-}" =~ ^[1-9][0-9]*$ && "${DEV_GID:-}" =~ ^[0-9]+$ ]] ||
        fail "DEV_UID/DEV_GID missing or invalid; launch it with c -k"
    uid="${DEV_UID}"
    gid="${DEV_GID}"
    unset DEV_UID DEV_GID
    IFS=: read -r name _ _ account_gid _ home _ < <(getent passwd "${uid}") ||
        fail "uid ${uid} has no account in the image; rebuild it with dev-container/build.sh"
    [[ "${account_gid}" == "${gid}" ]] ||
        fail "uid ${uid} has primary gid ${account_gid}, not ${gid}; rebuild the image with dev-container/build.sh"

    # libkrunfw's guest kernel ships CONFIG_LEGACY_TIOCSTI=y
    echo 0 >/proc/sys/dev/tty/legacy_tiocsti
    [[ "$(</proc/sys/dev/tty/legacy_tiocsti)" == 0 ]] || fail "cannot disable dev.tty.legacy_tiocsti"

    # virtio-fs passes files but not Unix-socket endpoints, so the signer is
    # reached over TCP: `c -k` has pasta forward guest connections on port 7777
    # to the host's loopback (see dev-container/README.md). Bridge it to the
    # socket path SSH_AUTH_SOCK expects; /run rejects the bind in the guest,
    # hence /tmp. The socket is owned by the workload user so agent-sandbox's
    # invoker-ownership check accepts it.
    if [[ -n "${GIT_SIGNING_DISABLED:-}" ]]; then
        unset SSH_AUTH_SOCK
    else
        socat "UNIX-LISTEN:/tmp/ssh-agent.sock,fork,mode=0600,user=${uid},group=${gid}" TCP:127.0.0.1:7777 &
        bridge_pid=$!
        if ! timeout 3s bash -c '
            while kill -0 "$1" 2>/dev/null; do
                [[ -S /tmp/ssh-agent.sock ]] && exit 0
                sleep 0.05
            done
            exit 1
        ' bash "${bridge_pid}"; then
            echo "entrypoint: warning: signing agent socket did not become ready; running without SSH_AUTH_SOCK" >&2
            unset SSH_AUTH_SOCK
        fi
    fi
    # Podman derived HOME from the root start, not from the workload user
    export HOME="${home}" USER="${name}" LOGNAME="${name}"
    exec setpriv --reuid="${uid}" --regid="${gid}" --init-groups -- "$@"
fi

exec "$@"
