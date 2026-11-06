# Integrations

Contents: [Network modes](#network-modes) · [pasta](#pasta) · [Terminal policy](#terminal-policy) · [Wayland](#wayland) · [GPU](#gpu) · [Out of scope](#out-of-scope) · [Helper lifecycle](#helper-lifecycle) · [Secrets](#secrets)

## Network modes

| Mode | bwrap options | Grants | Use for |
|---|---|---|---|
| `none` (default) | `--unshare-net` (included in `--unshare-all`) | Loopback inside the sandbox only; host loopback, LAN, internet and the host's abstract Unix sockets unreachable | Everything that does not need the network |
| `pasta` | `--unshare-all --share-net` under a pasta prefix | Outbound connections through host routing (VPN included); no inbound connections; host loopback unreachable except explicitly forwarded ports | Applications that need the internet, in the compromised and hostile tiers |
| `host` | `--share-net` | The host network stack: every host loopback service (databases, dev servers, container-engine APIs), the LAN, and every abstract Unix socket, including X11's `@/tmp/.X11-unix/X*` | Only when the access table justifies it and the user accepts the exposure |

Pathname Unix sockets are filesystem policy in every mode: a socket reachable through a bind is reachable regardless of the network namespace.
None of the modes filters destinations; pasta is not an allowlist, and a domain allowlist needs a filtering proxy, which is outside this skill.

## pasta

pasta (from the `passt` package) creates a user and a network namespace, runs its command inside them, and relays traffic through host sockets.

```text
/usr/bin/pasta --config-net -t none -u none -T none -U none --no-map-gw \
    --dns-forward 169.254.1.1 -- <stage> /usr/bin/bwrap \
    --unshare-all --share-net --unshare-user --uid "$UID" --gid "$GID" \
    --disable-userns --cap-drop ALL ... -- <command>
```

- pasta's defaults do not isolate: `-t`, `-u`, `-T` and `-U` default to forwarding every bound port automatically, and the gateway address maps to host loopback. Pass `-t none -u none -U none --no-map-gw` always.
- `-T PORTS` (comma-separated) makes `127.0.0.1:<port>` and `[::1]:<port>` inside the sandbox reach the same host loopback port; use it for the explicit host services in the access table, else `-T none`. `-t` would forward inbound connections from the host into the sandbox.
- bwrap runs as uid 0 inside pasta's user namespace, so it needs `--unshare-user --uid <uid> --gid <gid>` to drop back to the user's ids, and `--cap-drop ALL` to drop the capabilities it would otherwise keep.
- In normal operation pasta closes every inherited descriptor above 2 (with `close_range`) before running its command, so descriptors for `--args`, `--seccomp` or `--ro-bind-data` cannot be opened before pasta. Pass host-only file paths instead and let a stage between pasta and bwrap open them as descriptors: `/bin/sh -c`, or `/usr/bin/python3 -I -c` when it must also open bind sources without following symlinks (see [Secrets](#secrets) and the Python asset).
- `--dns-forward ADDR` makes pasta answer DNS at `ADDR` using the host's resolver; generate a `resolv.conf` with `nameserver ADDR` and bind it at the resolved path of `/etc/resolv.conf` (see [filesystem.md](filesystem.md#dns-configuration)).
- On Fedora, pasta runs in SELinux's `pasta_t` domain and the stage it runs returns to the user's domain. `pasta_t` may not write the user's regular files, so give pasta a pipe or `/dev/null` instead of a log file. Upstream policy allows user terminals, but confirm on the host that an interactive terminal works through pasta.
- pasta exits with its command's status, but it does not forward signals: SIGTERM to pasta makes pasta exit without signalling its command, and on Fedora SELinux denies the parent-death signal from `pasta_t` to bwrap, so killing pasta alone can leave the sandbox running without network. See [Helper lifecycle](#helper-lifecycle).
- `pasta --version` prints a date-based version whose form differs between upstream (`2025_04_15.<hash>`) and Fedora (`0^20261002.g<hash>`); parse the date when a launcher depends on a minimum release.

## Terminal policy

| Application's terminal needs | Policy |
|---|---|
| Not interactive (batch tool, service, GUI) | `--new-session`; stdin from `/dev/null` or a pipe, stdout and stderr to a pipe or log |
| Interactive, but works without a controlling terminal | `--new-session`, then confirm on the host that input, output and resizing behave acceptably |
| Needs the host's controlling terminal (job control, resize, an agent TUI that misbehaves under `--new-session`) | No `--new-session`; the masked TIOCSTI/TIOCLINUX seccomp filter from [seccomp.md](seccomp.md) is mandatory in every tier, which makes the launcher Python; also require `dev.tty.legacy_tiocsti=0` when `/proc/sys/dev/tty/legacy_tiocsti` exists |

What `--new-session` changes: the sandbox has no controlling terminal, so it receives no `SIGWINCH` on resize and no job-control signals (`Ctrl-Z`, and `Ctrl-C` unless the application reads raw input). The terminal descriptors are still inherited, so a raw-mode TUI may work; verify input, resize, cancellation, suspension and terminal restoration on the host.

Why the filter is mandatory without it:

- TIOCSTI pushes bytes into the terminal's input queue, so sandboxed code can type commands into the host shell after it exits (CVE-2017-5226).
- TIOCLINUX does the same on Linux virtual consoles through selection pasting (CVE-2023-28100).
- The rule must compare only the low 32 bits of the ioctl request, as the kernel does; an unmasked rule is bypassed by setting high bits (CVE-2019-10063).
- `legacy_tiocsti=0` (kernels 6.2 and later) disables TIOCSTI for unprivileged callers but not TIOCLINUX, so it complements the filter rather than replacing it.

Process-group signals, a residual risk without `--new-session`:

- The sandbox inherits the launcher's process group, and a PID namespace does not stop `kill(0, sig)` reaching the other members of that group (reasoned from Linux 6.12's `kernel/signal.c`; not reproduced on a host).
- Under an interactive job-control shell the group is the launcher's own job (the launcher, pasta, bwrap), so the impact is the sandbox killing its own supervision.
- When a script without job control runs the launcher, the group can include the calling script; list this in the residual risks.
- The probe check `pgrp-isolated` reports whether the group or session was allocated outside the sandbox; it does not show whether another member is alive or whether a signal would be delivered.

## Wayland

Binding the compositor socket directly gives the application every global the compositor advertises, which on wlroots compositors such as Sway includes screen capture, virtual keyboard and pointer input, and clipboard control.

Require the `wp_security_context_manager_v1` protocol, and fail closed when the compositor lacks it:

1. The launcher connects to the compositor and binds `wp_security_context_manager_v1`.
2. It creates a listening Unix socket in a host-only directory and a pipe whose read end is the close descriptor, and calls `create_listener` with both, setting the sandbox engine and application id metadata and committing.
3. It connects to the new socket itself and compares the advertised globals against an allowlist for that compositor version, aborting on anything else.
4. It binds only that socket into the sandbox as `/run/user/<uid>/wayland-0` and sets `WAYLAND_DISPLAY=wayland-0` and `XDG_SESSION_TYPE=wayland`, with no `DISPLAY`.
5. The compositor revokes the listener when the close descriptor's write end closes, so the launcher keeps it open for the sandbox's lifetime.

`vscode-sandbox` implements this in about 200 lines of standard-library Python (Wayland wire protocol over `socket.socket` with `SCM_RIGHTS`) for Sway 1.11; read its `Wayland` class, `create_security_context` and `audit_globals` before writing a new one.
Electron applications also need `--ozone-platform=wayland`, and lose their own sandbox under `--disable-userns` (`--no-sandbox`); record that trade-off.

## GPU

- `--dev-bind` each `/dev/dri/renderD*` node at its own path; never the primary `card*` nodes, which allow display mode-setting.
- `--ro-bind` `/sys/block`, `/sys/bus`, `/sys/class`, `/sys/dev` and `/sys/devices` (Flatpak's set) so Mesa can discover the device.
- Accept a software-rendering fallback when acceleration fails rather than widening device access.

## Out of scope

X11, D-Bus (including xdg-dbus-proxy filtering and portals), PipeWire and PulseAudio audio, and ALSA devices are not covered.
When an application needs one, tell the user what it would grant (X11 allows keylogging and input injection into every client; a session bus socket can make systemd run arbitrary host commands) and stop rather than binding the raw socket.

## Helper lifecycle

Prefer an `exec` chain: launcher → pasta → stage → bwrap → application, with every link `exec`ing the next or running it as its only child.
The exit status then propagates, and terminal-generated signals (hangup, `Ctrl-C`) reach the whole foreground process group when the terminal is shared.
Signals sent to one process do not propagate: bwrap forwards nothing to its child, pasta does not forward signals, and `--die-with-parent` ties the sandbox only to its immediate parent, which SELinux can block (above).
Accept the chain for foreground interactive use after the lifecycle checks in [verification.md](verification.md#application-acceptance) pass on the host; supervise when they fail or when the launcher must guarantee teardown.

Write a supervising Python launcher only when the launcher must outlive the exec (readiness reporting, a detached GUI, cleanup of host-side files, a Wayland close descriptor):

- Use `--sync-fd` or `--json-status-fd` to learn when the sandbox ends, and `--block-fd` to hold the command until a helper is ready.
- Remember that parent-death signals are per thread and cleared by SELinux transitions; a child subreaper (`PR_SET_CHILD_SUBREAPER`) plus pidfds is the robust teardown, as in `vscode-sandbox`'s guard process.
- Take an `flock` in a host-only directory under `$XDG_RUNTIME_DIR` for single-instance launchers; the lock dies with its holder.

## Secrets

`--setenv NAME VALUE` puts the value in bwrap's command line, which every local user can read in `/proc/<pid>/cmdline`.
Pass every option that carries a secret through `--args FD` instead:

- Python without pasta: write the NUL-separated options to `os.memfd_create`, rewind, mark it inheritable, and pass `--args <fd>` (`agent-sandbox`'s `exec_sandbox`).
- Bash without pasta: `--args 3 3< <(printf '%s\0' --setenv API_KEY "${API_KEY}")`.
- With pasta, which closes inherited descriptors: write the options to a mode-0600 file in a per-launch mode-0700 directory under `$XDG_RUNTIME_DIR`, have the stage open it on a descriptor and delete it before `exec`ing bwrap (`exec 3<"$1"; rm -f -- "$1"; shift; exec "$@"`), and pass `--args 3`. When the stage must also open bind sources without following symlinks (for `--bind-fd`), write it as `/usr/bin/python3 -I -c`, as the Python asset does.
- Redact the values in `--dry-run` and debug output; print the descriptive options there instead of the descriptor.
