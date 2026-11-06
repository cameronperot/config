# bwrap semantics

Contents: [Model](#model) · [Argument processing](#argument-processing) · [Namespaces](#namespaces) · [Process lifetime](#process-lifetime) · [Capabilities](#capabilities) · [Confusable options](#confusable-options) · [Version and feature detection](#version-and-feature-detection) · [Sources and refresh](#sources-and-refresh)

## Model

- bwrap starts from an empty tmpfs root in a new mount namespace, applies the filesystem options in command-line order, pivots into the result and execs the command.
- Nothing from the host is visible unless an option puts it there; every bind mount gets `nosuid` and, except `--dev-bind`, `nodev`.
- bwrap sets `PR_SET_NO_NEW_PRIVS` itself, so setuid binaries inside cannot gain privileges; there is no launcher flag for it.
- bwrap 0.12.0 removed setuid support and refuses to run when installed setuid; it needs unprivileged user namespaces.
- The upstream README and SECURITY policy state that bwrap is not a ready-made sandbox: the program constructing the arguments defines the security model.

## Argument processing

- Repetition is per option. Some accumulate (`--args`, `--overlay-src`, `--add-seccomp-fd`, `--lock-file`, `--sync-fd` since 0.13.1, and every filesystem operation). The man page says the last occurrence of the others wins, but bwrap 0.13.1 exits with an error on a repeated `--argv0` and on `--perms` or `--size` given twice before the same operation. Never repeat an option the launcher does not mean to accumulate.
- `--` ends bwrap's options; without it, a command beginning with `--` is parsed as a bwrap option (Flatpak CVE-2024-32462).
- Since 0.13.0, an empty path argument is an error; earlier releases sometimes treated it as `/`. Validate that every path variable is non-empty before building the argv anyway, and use `set -u` in Bash.
- `--args FD` reads NUL-separated options from a descriptor, closes it, and splices them in place; it cannot be nested inside another `--args` file.
- Put only options in the `--args` data; keep `--` and the command on the real argv, as `agent-sandbox` does.
- `--perms OCTAL` and `--size BYTES` modify only the next operation (`--perms` for `--dir`, `--tmpfs`, `--file`, `--bind-data` and `--ro-bind-data`; `--size` for `--tmpfs`), and do not persist.
- Filesystem operations run in argument order; see [filesystem.md](filesystem.md#mount-order) for the ordering rules.
- `--chdir DIR` sets the working directory; without it, bwrap keeps the current directory when it exists inside, else falls back to `$HOME`.

## Namespaces

| Option | Effect | Notes |
|---|---|---|
| `--unshare-all` | `--unshare-user-try --unshare-ipc --unshare-pid --unshare-net --unshare-uts --unshare-cgroup-try` | The user and cgroup parts are *try* variants and can silently be skipped |
| `--unshare-user` | Mandatory new user namespace | Required by `--disable-userns`, `--uid` and `--gid`; bwrap adds it automatically only when the real uid is not 0 |
| `--disable-userns` | Sets `user.max_user_namespaces` to 1 and enters a nested namespace, so the sandbox cannot create user namespaces | Implies the `--assert-userns-disabled` check; incompatible with `--userns-block-fd`; breaks applications that sandbox themselves with user namespaces (Chromium, Electron, Flatpak, nested bwrap) |
| `--assert-userns-disabled` | Only checks that user namespaces cannot be created | For namespaces prepared outside bwrap (`--userns FD`); redundant next to `--disable-userns` |
| `--unshare-pid` | New PID namespace with bwrap as PID 1 reaping zombies; the command is PID 2 | `--proc` mounts a fresh procfs only with this or `--pidns`; otherwise it binds the host's `/proc` |
| `--unshare-net` | New network namespace with only loopback | Also isolates abstract Unix sockets, which are scoped per network namespace |
| `--share-net` | Undoes an earlier `--unshare-net` or `--unshare-all` | Use with pasta, which owns the network namespace, or for the explicit `host` network mode |
| `--unshare-ipc` | Private SysV IPC and POSIX message queues | Does not isolate `/dev/shm` or sockets; that is filesystem policy |
| `--unshare-uts` | Private hostname | Required by `--hostname` |
| `--unshare-cgroup` | Private view of the cgroup hierarchy | Visibility only; resource limits need `systemd-run --user -p MemoryMax=…` or `prlimit` around the launcher |
| `--uid UID`, `--gid GID` | Ids inside the sandbox | Required when bwrap runs as uid 0 in an outer user namespace (pasta, Podman), or the application runs as root inside |
| `--userns FD`, `--pidns FD`, `--userns2 FD` | Join existing namespaces | Advanced; the namespace must be owned by the caller |

## Process lifetime

- bwrap's exit status is the command's (PID 2), in shell encoding (`128+n` for signal `n`).
- `--as-pid-1` runs the command as PID 1 without bwrap's reaper; avoid it unless the command is an init.
- `--die-with-parent` sets `PR_SET_PDEATHSIG` so the sandbox gets SIGKILL when bwrap's parent dies. The signal fires when the parent *thread* exits, so spawn bwrap from the main thread or `exec` it. SELinux can deny the signal: on Fedora, bwrap's parent under pasta runs in `pasta_t`, whose parent-death signal to bwrap is denied (see [integrations.md](integrations.md#helper-lifecycle)).
- `--new-session` calls `setsid()`: the sandbox loses its controlling terminal, so TIOCSTI injection and process-group signals to the launcher's group stop working, and so do terminal resize signals and job control. See [integrations.md](integrations.md#terminal-policy).
- When stdout is a terminal, `--dev` adds `/dev/console` pointing at it; `--new-session` does not remove inherited terminal descriptors.
- `--sync-fd FD` keeps a descriptor open for the sandbox's lifetime, so a helper can detect its end; `--lock-file DEST` holds a lock on a sandbox path; `--block-fd FD` delays the command until data arrives; `--json-status-fd FD` reports the child PID and exit code as JSON lines (`--info-fd` is the older single-object form).

## Capabilities

- Unprivileged, bwrap leaves the command no capabilities.
- When the real uid is 0 and no `--cap-add`/`--cap-drop` is given, bwrap keeps the capabilities: a launcher whose bwrap may run as uid 0 inside another user namespace gets root-in-namespace powers unless it passes `--cap-drop ALL`.
- `--cap-add` and `--cap-drop` are processed in order and accept `ALL`.

## Confusable options

| Option | What it really does |
|---|---|
| `--ro-bind`, `--bind` | Recursive bind; read-only and `nosuid`/`nodev` flags are reapplied to every submount, and a submount that cannot be remounted (other than for EACCES) aborts the launch. Mounts propagated in later, such as a newly inserted USB drive, do not get the flags |
| `--ro-bind-try`, `--bind-try`, `--dev-bind-try` | Skip a *missing source* only; use them for genuinely optional resources, never for required pins |
| `--bind-fd FD DEST`, `--ro-bind-fd FD DEST` | Bind an already-open `O_PATH` descriptor, so the source cannot be swapped between check and mount; listed in `--help` since 0.10.0 but missing from the man page |
| `--file FD DEST` | Copies the descriptor's contents into a new file, mode 0666 unless `--perms` precedes it |
| `--bind-data FD DEST`, `--ro-bind-data FD DEST` | Copies the contents into a hidden file bind-mounted at `DEST`, mode 0600 unless `--perms` precedes it; use `--ro-bind-data` for generated configuration such as `passwd` or `resolv.conf` |
| `--dir DEST` | Creates a directory; an existing directory keeps its mode, ignoring `--perms` |
| `--chmod OCTAL PATH` | Changes an existing inode; inside a writable host bind this changes the host file |
| `--tmpfs DEST` | New tmpfs, mode 0755 unless `--perms`; without `--size` the kernel default applies (half of physical RAM) |
| `--remount-ro DEST` | Remounts exactly that mount point read-only, not the mounts below it |
| `--dev DEST` | New tmpfs with `null`, `zero`, `full`, `random`, `urandom`, `tty`, a private `devpts` with `ptmx`, `fd`/`stdin`/`stdout`/`stderr` links and an `shm` directory on the same tmpfs, which serves POSIX shared memory; mount `--size N --tmpfs /dev/shm` only to cap it separately |
| `--dev-bind SRC DEST` | Bind without `nodev`; the only way to expose a device node such as `/dev/dri/renderD128` |
| `--proc DEST` | Fresh procfs only with a bwrap PID namespace; otherwise a bind of the host's `/proc` |
| `--symlink TARGET DEST` | Since 0.9.0 an identical existing symlink is not an error |
| `--overlay-src`, `--overlay`, `--tmp-overlay`, `--ro-overlay` | Overlayfs since 0.11.0; sources stack bottom-up in command-line order (the reverse of the kernel's `lowerdir`); no source may be an ancestor of another; copy-on-write, not confidentiality |
| `--seccomp FD`, `--add-seccomp-fd FD` | Load compiled cBPF; see [seccomp.md](seccomp.md) |
| `--level-prefix` | Prefixes diagnostics with syslog levels for `systemd-cat --level-prefix=1`; since 0.11.0 |

## Version and feature detection

1. Resolve the bwrap the launcher will execute to its absolute path.
2. Parse `bwrap --version` (`bubblewrap X.Y.Z`) and require at least 0.12.0.
3. Check every option token the launcher uses against that binary's `--help` output; the man page is not complete.
4. Read the release notes for semantic changes behind unchanged option names, such as multiple `--sync-fd` (0.13.1) or empty-path rejection (0.13.0).
5. Fail with an actionable message when a required feature is missing; never drop the option and continue.

Release history relevant to launchers, from bubblewrap 0.13.1's NEWS and earlier release notes:

| Release | Change |
|---|---|
| 0.8.0 | `--disable-userns`, `--assert-userns-disabled` |
| 0.9.0 | Identical `--symlink` no longer an error |
| 0.10.0 | `--bind-fd`, `--ro-bind-fd` |
| 0.11.0 | Overlay options, `--level-prefix` |
| 0.11.2 | Setuid support off in default builds |
| 0.12.0 | Setup no longer follows sandbox-controlled symlinks out of the new root (GHSA-pxhw-h44j-8pfx); setuid support removed; `--not-a-security-boundary` added |
| 0.13.0 | Empty path arguments rejected; `mount_setattr` used on kernels 5.12 and later |
| 0.13.1 | Multiple `--sync-fd` |

Debian 12 ships a release older than 0.12.0 and Debian declined to backport the fix, so launchers refuse to run there.

## Sources and refresh

Claims here come from bubblewrap 0.13.1: its README, SECURITY policy, man page source (`bwrap.xml`), `--help` text and implementation (`bubblewrap.c`, `bind-mount.c`), NEWS, and its test suite (`tests/try-syscall.c`, `tests/test-seccomp.py`).
Flatpak's 2024 advisories supplied the `--` and symlink-swap lessons.

When bwrap, Flatpak, pasta or the kernel changes:

1. Read the new bubblewrap NEWS and diff `bwrap --help` against the option tables here.
2. Re-check the Flatpak release's seccomp filter against [seccomp.md](seccomp.md).
3. Read new bubblewrap and Flatpak security advisories for lessons that apply to launchers.
4. Re-run the probe checks in [verification.md](verification.md) against the bundled examples on a host.
5. Update the version numbers named in these references.
