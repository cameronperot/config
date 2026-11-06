#!/bin/bash
#
# example-cli.sh — run an offline CLI tool in a Bubblewrap sandbox that sees the
# working directory read-only, a private cache, and nothing else of $HOME.
#
# Usage: example-cli.sh [-v] [--dry-run] [--debug] [--exec -- CMD...] [--] [ARGS...]
#
# Tier: accidental damage. Access table:
#   /usr, /etc            ro     host system, libraries, configuration
#   /bin /sbin /lib*      link   mirrored from the host
#   $PWD                  ro     the tool's input
#   ~/.cache/example      rw     persistent, from ~/.local/share/example-sandbox
#   $HOME /tmp /run       tmpfs  ephemeral
#   network               none
# Residual risks: reads everything in $PWD and /etc; kernel vulnerabilities.
#
# The interpreter and every utility resolve to system paths: the caller's PATH
# can contain project directories the sandbox writes, such as an active .venv.

set -euo pipefail

PATH=/usr/bin:/bin
export PATH

readonly BWRAP=/usr/bin/bwrap
readonly TOOL=/usr/bin/example-tool
readonly MIN_BWRAP=0.12.0

dry_run=0
verbose=0
command=("${TOOL}")
home=""
cwd=""
argv=()

usage() {
    cat <<EOF
Usage: ${0##*/} [options] [ARGS...]

Run ${TOOL##*/} sandboxed: \$PWD read-only, no network, no home directory.

Options:
  -h, --help        show this help
  -v, --verbose     report decisions on stderr
  --dry-run         print the bwrap command without creating state or running
  --debug           trace execution (set -x)
  --exec -- CMD...  run CMD instead of ${TOOL##*/} under the same policy

Examples:
  ${0##*/} input.txt
  ${0##*/} --exec -- /usr/bin/python3 -I - hidden:\$HOME/.ssh <probe.py
EOF
}

die() {
    echo "${0##*/}: error: $*" >&2
    exit 1
}
log_verbose() { if ((verbose)); then echo "${0##*/}: $*" >&2; fi; }

#######################################
# Resolve $HOME and the working directory physically and refuse to expose /,
# $HOME or an ancestor of it.
# Globals: HOME, home, cwd (modified)
#######################################
resolve_paths() {
    [[ -n "${HOME:-}" ]] || die "HOME is not set"
    home="$(cd -- "${HOME}" && pwd -P)" || die "cannot resolve ${HOME}"
    cwd="$(pwd -P)" || die "cannot resolve the working directory"
    [[ "${home}" != / ]] || die "HOME must not be /"
    # Physical paths, so a symlinked alias of $HOME cannot pass the check
    [[ "${home}/" != "${cwd%/}/"* ]] || die "refusing to expose ${cwd}"
}

#######################################
# Create the persistent store below $HOME, refusing symlinked or foreign
# components so the bind cannot be redirected.
# Globals: home
# Arguments: the store path relative to $HOME
#######################################
ensure_store() {
    local path="${home}" part
    local -a parts
    IFS=/ read -r -a parts <<<"$1"
    for part in "${parts[@]}"; do
        path="${path}/${part}"
        [[ ! -L "${path}" ]] || die "${path} is a symlink"
        if [[ ! -e "${path}" ]]; then
            mkdir -m 0700 -- "${path}"
        fi
        [[ -d "${path}" && -O "${path}" ]] || die "${path} is not your directory"
    done
}

#######################################
# Build the bwrap argv for the command.
# Globals: BWRAP, home, cwd, command; argv (modified)
#######################################
build_argv() {
    local top store="${home}/.local/share/example-sandbox"
    argv=("${BWRAP}" --unshare-all --unshare-user --disable-userns
        --cap-drop ALL --die-with-parent --new-session --clearenv
        --ro-bind /usr /usr --ro-bind /etc /etc)
    # Mirror merged-/usr links instead of assuming the host's layout
    for top in /bin /sbin /lib /lib64 /lib32 /libx32; do
        if [[ -L "${top}" ]]; then
            argv+=(--symlink "$(readlink "${top}")" "${top}")
        elif [[ -d "${top}" ]]; then
            argv+=(--ro-bind "${top}" "${top}")
        fi
    done
    argv+=(--proc /proc --dev /dev --tmpfs /tmp --tmpfs /run
        --tmpfs "${home}" --ro-bind "${cwd}" "${cwd}"
        --bind "${store}/cache" "${home}/.cache/example"
        --setenv HOME "${home}" --setenv PATH /usr/bin:/bin
        --setenv LANG "${LANG:-C.UTF-8}" --chdir "${cwd}"
        -- "${command[@]}")
}

#######################################
# Fail unless bwrap is new enough and supports every option in argv.
# Globals: BWRAP, MIN_BWRAP, argv, command
#######################################
preflight() {
    local version help arg
    [[ -x "${BWRAP}" ]] || die "${BWRAP} not found; install bubblewrap"
    [[ -x "${command[0]}" ]] || die "${command[0]} not found"
    version="$("${BWRAP}" --version)"
    version="${version##* }"
    [[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        || die "cannot parse bwrap version ${version}"
    printf '%s\n%s\n' "${MIN_BWRAP}" "${version}" | sort -V -C \
        || die "bubblewrap ${version} is older than ${MIN_BWRAP}"
    help="$("${BWRAP}" --help)"
    # Every option token before the command separator, so the check cannot drift
    for arg in "${argv[@]:1}"; do
        [[ "${arg}" != -- ]] || break
        if [[ "${arg}" == --* && "${help}" != *"${arg} "* ]]; then
            die "bwrap lacks ${arg}"
        fi
    done
}

# Inherited descriptors would bypass the mount and network policy
close_inherited_fds() {
    local fd number
    for fd in /proc/self/fd/*; do
        number="${fd##*/}"
        if ((number > 2)); then
            exec {number}>&-
        fi
    done
}

main() {
    local -a args=()
    while (($# > 0)); do
        case "$1" in
        -h | --help) usage && exit 0 ;;
        -v | --verbose) verbose=1 && shift ;;
        --dry-run) dry_run=1 && shift ;;
        --debug) set -x && shift ;;
        --) shift && args=("$@") && break ;;
        --exec)
            [[ "${2:-}" == "--" && $# -ge 3 ]] || die "--exec needs -- CMD"
            shift 2
            command=("$@")
            break
            ;;
        *) args=("$@") && break ;;
        esac
    done
    command+=("${args[@]}")
    resolve_paths
    build_argv
    preflight
    if ((dry_run)); then
        printf '%q ' "${argv[@]}" && echo
        exit 0
    fi
    log_verbose "checking ${home}/.local/share/example-sandbox/cache"
    ensure_store .local/share/example-sandbox/cache
    close_inherited_fds
    exec "${argv[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
