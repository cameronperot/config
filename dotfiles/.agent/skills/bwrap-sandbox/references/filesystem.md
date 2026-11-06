# Filesystem policy

Contents: [Baseline layout](#baseline-layout) · [Top-level links](#top-level-links) · [/etc](#etc) · [DNS configuration](#dns-configuration) · [Home and persistent state](#home-and-persistent-state) · [Mount order](#mount-order) · [Writable roots](#writable-roots) · [Host-executed files](#host-executed-files) · [Symlink swaps](#symlink-swaps) · [Descriptor-backed files](#descriptor-backed-files) · [Overlays](#overlays)

## Baseline layout

| Sandbox path | Operation | Why |
|---|---|---|
| `/usr` | `--ro-bind /usr /usr` | Binaries and libraries from the host, so the launcher needs no runtime of its own |
| `/bin`, `/sbin`, `/lib`, `/lib64`, `/lib32`, `/libx32` | Mirror the host (below) | The dynamic loader and `#!/bin/sh` scripts need them |
| `/etc` | `--ro-bind /etc /etc`, or the curated variant | Loader cache, NSS, certificates, time zone, resolver |
| `/proc` | `--proc /proc` with `--unshare-pid` | A fresh procfs shows only sandbox processes |
| `/dev` | `--dev /dev` | Private device set, devpts and a `/dev/shm` for POSIX shared memory |
| `/tmp`, `/run` | `--tmpfs` each | Hides host sockets, the display server's sockets, other users' files |
| `/run/user/<uid>` | `--perms 0700 --dir /run/user/<uid>`, and set `XDG_RUNTIME_DIR` | Applications expect it; only the sockets the access table grants go inside |
| `$HOME` | `--tmpfs "$HOME"` | Hides keys, credentials, browser profiles and other projects |
| Project or working directory | `--bind` or `--ro-bind` at the same path, per the access table | Same path keeps tools that record absolute paths consistent |

Do not add `/var`, `/sys`, `/opt`, `/srv`, `/media` or `/mnt` by default; add a specific subtree only for an access-table row (for example `/opt/<toolchain>` read-only, or the `/sys` subset in [integrations.md](integrations.md#gpu)).

## Top-level links

Fedora and Debian 12 and later use merged `/usr`: `/bin`, `/sbin`, `/lib` and `/lib64` are symlinks into `/usr`.
Mirror what the host actually has rather than hard-coding a layout:

- Host path is a symlink: `--symlink "$(readlink /bin)" /bin`.
- Host path is a real directory: `--ro-bind /bin /bin`.
- Host path is absent (for example `/lib32` on most systems): skip it.

Missing `/lib64` shows up as `bwrap: execvp <command>: No such file or directory` for a binary that exists, because the ELF interpreter `/lib64/ld-linux-x86-64.so.2` is missing.

## /etc

Default: bind the whole of `/etc` read-only.
It exposes only what the invoking user can already read, mostly harmless host configuration, and avoids per-distribution breakage.

Curated variant, for strict policies: bind only what the application needs, typically:

- `ld.so.cache`, `ld.so.conf`, `ld.so.conf.d`.
- `alternatives` on Debian, because many `/usr/bin` entries are symlinks into `/etc/alternatives`.
- `nsswitch.conf`, `hosts`, `host.conf`, `gai.conf`, and the resolver (below).
- `ssl`, plus `pki` and `crypto-policies` on Fedora, plus `ca-certificates` on Debian.
- `localtime`, `os-release`, `mime.types`, `fonts` for GUI applications.
- Synthetic `passwd` and `group` containing only the invoking user and `nobody`, via `--ro-bind-data` (below).

A curated `/etc` breaks in application-specific ways; debug it on the host with the probe script and the application itself.

## DNS configuration

`/etc/resolv.conf` is often a symlink into `/run` (systemd-resolved's `/run/systemd/resolve/stub-resolv.conf`, NetworkManager's `/run/NetworkManager/resolv.conf`), which a tmpfs `/run` hides.
Resolve the link on the host, create the target's parents under `/run` with `--dir`, and `--ro-bind` the resolved file at its resolved path, as `vscode-sandbox`'s `resolv_args` does.

systemd-resolved's stub listens on `127.0.0.53` in the host network namespace, so it is unreachable under `none` and `pasta`.
For `pasta`, generate a `resolv.conf` naming pasta's DNS forwarder (see [integrations.md](integrations.md#network-modes)) and bind it with `--ro-bind-data` at the resolved path.

## Home and persistent state

- Start from `--tmpfs "$HOME"`; writes outside the persistent binds vanish when the sandbox exits.
- Add read-only binds for toolchains the application runs (`~/.local/bin`, a uv or micromamba tree) with `--ro-bind-try` only when they are optional.
- Keep persistent application state in a dedicated host store, for example `~/.local/share/<name>-sandbox/<subdir>`, bound onto the paths the application uses.
- Create the store on the host before launch, and check that every component is a directory owned by the user and not a symlink.
- Never bind the application's real host configuration read-write when host-side software later reads it as code or policy (hooks, plugins, MCP servers, extension directories, `settings.json`); bind those entries read-only on top of the writable store instead, as `agent-sandbox` pins agent configuration.
- Keep the launcher itself, its helpers and every directory on the sandbox's `PATH` outside writable binds.

## Mount order

bwrap applies filesystem operations in argument order, and a later mount hides whatever an earlier one put below it.

1. System trees and mounts that cover a parent (`/usr`, `/etc`, `--tmpfs /tmp /run "$HOME"`).
2. Read-only roots and toolchains inside those parents.
3. Writable roots and the persistent store.
4. Read-only pins inside writable areas (for example a protected config file inside a writable store).
5. `--remount-ro` of parents that must stay read-only after their children were mounted.

Two side effects of order:

- bwrap creates missing mount points; inside a writable host bind it creates them on the host, leaving empty files or directories behind.
- bwrap cannot create a missing mount point inside a read-only bind (`Can't create file <dest>` or `Can't mkdir parents for <dest>` with `Read-only file system`), so the mount point must already exist on the host, or the read-only parent must become a tmpfs with selective binds.

## Writable roots

When a user or the working directory chooses a writable root (a project, a `--rw DIR` flag), validate it in Python before launch:

1. Resolve it fully (every symlink followed) and require an existing directory and a non-empty path.
2. Reject `/`, `$HOME`, and any ancestor of `$HOME`.
3. Reject system trees and their descendants: `/usr /bin /sbin /lib /lib64 /etc /opt /var /boot /root /srv /tmp /run /proc /sys /dev`.
4. Reject anything under a top-level hidden entry of `$HOME` (`~/.ssh`, `~/.config`, `~/.local`), checking both the lexical and the resolved path.
5. Reject overlap in either direction with protected paths: the launcher, its helpers, read-only pins, the persistent store's protected entries.

`agent-sandbox` and `vscode-sandbox` implement these checks; read their path-validation functions for edge cases such as Git worktrees with an external common directory.

## Host-executed files

A writable root lets sandboxed code plant content that the host later executes outside the sandbox:

- `.git/hooks/*`, and `.git/config` keys such as `core.fsmonitor`, `core.hooksPath`, `core.sshCommand` and `credential.helper`, run by host Git.
- `.envrc` (direnv), `.venv/bin/*`, `Makefile`, `package.json` scripts, `.pre-commit-config.yaml`, editor and agent settings in the project.
- Application plugin and extension directories that an unsandboxed instance also loads.

Choose per access table: bind `.git` read-only on top of a writable worktree (the agent cannot commit; commit from the host), or accept the exposure and list it in the residual risks so the user reviews `git status --ignored` and hooks after a session.
A `.git` inside a writable root is itself sandbox-controlled: refuse to launch when it is a symlink, because binding it would expose whatever it points to (see [Symlink swaps](#symlink-swaps)).

## Symlink swaps

A bind *source* inside a directory the sandbox can write (the persistent store, a writable root) can be replaced by a symlink between runs, so the next launch binds whatever it points to (Flatpak CVE-2024-42472).

- Never take bind sources from sandbox-writable trees when a path-based check is enough to fool.
- In Python, open the source component by component with `O_PATH | O_NOFOLLOW` (or `openat2` with `RESOLVE_NO_SYMLINKS`), check ownership with `fstat`, and pass the descriptor with `--bind-fd`/`--ro-bind-fd`, keeping it inheritable.
- Behind pasta, which closes inherited descriptors, open it in the stage between pasta and bwrap; the Python asset's stage does this for the project's `.git`.
- A check by path followed by a bind by path leaves a race that a concurrently running instance of the same sandbox can win.
- Canonicalising a path once and binding by name does not protect against concurrent replacement.

## Descriptor-backed files

Generate files from the launcher instead of exposing host files:

```bash
exec /usr/bin/bwrap \
    --ro-bind-data 11 /etc/passwd \
    --ro-bind-data 12 /etc/group \
    ... \
    11< <(getent passwd "$(id -u)" 65534) \
    12< <(getent group "$(id -g)" 65534)
```

In Python, write the content to a pipe or `os.memfd_create` descriptor, mark it inheritable, and pass its number.

## Overlays

`--tmp-overlay DEST` with `--overlay-src SRC` gives a writable view of a host directory whose writes are discarded at exit, useful for tools that insist on writing next to their inputs.
`--overlay RWSRC WORKDIR DEST` persists writes to `RWSRC`; `WORKDIR` must be an empty directory on the same filesystem.
Lower layers stay readable, so overlays are not a confidentiality mechanism.
