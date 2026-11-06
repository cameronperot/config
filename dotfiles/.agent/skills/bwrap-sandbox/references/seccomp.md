# Seccomp

Contents: [How bwrap loads filters](#how-bwrap-loads-filters) · [When a filter is required](#when-a-filter-is-required) · [Setup](#setup) · [Baseline filter](#baseline-filter) · [Building it](#building-it) · [Architectures](#architectures) · [Relaxations](#relaxations) · [Testing](#testing)

## How bwrap loads filters

- bwrap does not compile syscall lists; `--seccomp FD` loads a compiled classic BPF program, as produced by libseccomp's `seccomp_export_bpf`, from a descriptor.
- Given twice, `--seccomp` keeps only the last program.
- `--add-seccomp-fd FD` stacks programs, cannot be combined with `--seccomp`, and the kernel evaluates the last one first; every program except possibly the last must allow `prctl(PR_SET_SECCOMP)`.
- bwrap installs the filter after building the mounts, just before running the command, so the filter does not protect sandbox setup itself.
- Never ship an unexplained `.bpf` blob and never hand-write syscall numbers; build the program at launch from named rules.

## When a filter is required

| Situation | Filter |
|---|---|
| Hostile-code tier | Full baseline plus io_uring |
| Application keeps the host's controlling terminal (any tier) | At least the masked TIOCSTI/TIOCLINUX rules; the full baseline is recommended |
| Compromised-application tier | Recommended baseline; decide per application and record the decision |
| Accidental-damage tier | Optional |

## Setup

The launcher imports the libseccomp Python bindings (`import seccomp`), so the host needs them for the interpreter that runs the launcher:

- Fedora: `sudo dnf install libseccomp-python`.
- Debian: `sudo apt install python3-seccomp`.

Run the launcher with the system interpreter (`#!/usr/bin/python3 -I`) rather than a virtual environment, which would not see the distribution package.

## Baseline filter

Derived from Flatpak 1.18.4's filter for non-development applications without multiarch, as `vscode-sandbox` uses it; the default action is allow.

| Rule | Action | Reason |
|---|---|---|
| `syslog`, `uselib`, `acct`, `quotactl` | `EPERM` | Kernel log and legacy administration interfaces |
| `add_key`, `keyctl`, `request_key` | `EPERM` | The kernel keyring is not namespaced |
| `move_pages`, `mbind`, `get_mempolicy`, `set_mempolicy`, `migrate_pages` | `EPERM` | NUMA calls with a history of information leaks |
| `unshare`, `setns`, `mount`, `umount`, `umount2`, `pivot_root`, `chroot` | `EPERM` | No rearranging namespaces or mounts from inside |
| `clone` with any of `CLONE_NEWNS`, `CLONE_NEWCGROUP`, `CLONE_NEWUTS`, `CLONE_NEWIPC`, `CLONE_NEWUSER`, `CLONE_NEWPID`, `CLONE_NEWNET` (masked comparison on argument 0) | `EPERM` | Stricter than Flatpak, which denies only `CLONE_NEWUSER`; `CLONE_NEWTIME` is left out because its bit is `clone()`'s exit-signal field |
| `clone3` | `ENOSYS` | seccomp cannot inspect `clone3`'s flags in memory; `ENOSYS` makes libc fall back to `clone` |
| `open_tree`, `move_mount`, `fsopen`, `fsconfig`, `fsmount`, `fspick`, `mount_setattr` | `ENOSYS` | The new mount API (Flatpak CVE-2021-41133); `ENOSYS` makes callers fall back to the filtered legacy API |
| `modify_ldt` | `EPERM` | 16-bit segment tricks; only needed by multiarch (Wine) |
| `perf_event_open`, `ptrace` | `EPERM` | Profiling and process inspection; relax for debuggers and profilers |
| `ioctl` with request TIOCSTI or TIOCLINUX, compared with mask `0xFFFFFFFF` on argument 1 | `EPERM` | Terminal input injection; the mask closes CVE-2019-10063 |
| `personality` with argument 0 not equal to `PER_LINUX` | `EPERM` | Blocks personality flags that weaken address-space randomisation |
| `socket` with a family other than `AF_UNSPEC`, `AF_UNIX`, `AF_INET`, `AF_INET6`, `AF_NETLINK` | `EAFNOSUPPORT` | Removes rarely needed protocol families and their kernel code |

Hostile-code tier addition:

| Rule | Action | Reason |
|---|---|---|
| `io_uring_setup`, `io_uring_enter`, `io_uring_register` | `EPERM` | io_uring performs operations (including socket creation) that bypass per-syscall filtering, and is a large kernel attack surface; Anthropic's sandbox-runtime and OpenAI's Codex CLI sandbox block it too |

## Building it

`build_seccomp` in [../assets/example-interactive.py](../assets/example-interactive.py) implements the baseline table with the libseccomp bindings; reuse it rather than writing a new builder.
Key details it encodes:

- `add_rule`, not `add_rule_exactly`, for the deny lists, so a syscall missing on the running architecture (for example `umount` on aarch64) is skipped instead of failing the build.
- `seccomp.Arg(1, seccomp.MASKED_EQ, 0xFFFFFFFF, request)` for the ioctl rules, and `seccomp.Arg(0, seccomp.MASKED_EQ, flag, flag)` for each `clone` namespace flag.
- `add_rule_exactly` for the socket-family rules: one `EQ` rule per disallowed family below the highest allowed one, plus a `GE` rule above it.
- `bpf.export_bpf(file)` writes the program for bwrap.

For the hostile tier, add before exporting:

```python
for name in ("io_uring_setup", "io_uring_enter", "io_uring_register"):
    bpf.add_rule(seccomp.ERRNO(errno.EPERM), name)
```

- Write the program to a mode-0600 file in a host-only directory (or a memfd when no pasta prefix closes descriptors), open it on a descriptor that the bwrap process inherits, and pass `--seccomp <fd>`.
- A failure to import `seccomp` or to build the program aborts the launch with the install command; never launch without a required filter.
- On s390 the `clone` flags are argument 1; the rule above assumes argument 0 (x86_64, aarch64 and most other architectures).

## Architectures

- libseccomp filters only the native architecture unless `add_arch` is called, and its default bad-architecture action kills the process.
- So 32-bit binaries (i386 on x86_64, used by Wine and Steam) die immediately under this filter; that is safe, but it breaks them.
- This template does not support multiple architectures: libseccomp refuses `add_rule_exactly` (used for the socket-family rules) once a filter has several, and i386 creates sockets through the `socketcall` multiplexer, which these rules do not cover. A 32-bit application needs a separately designed and tested filter.

## Relaxations

Relax a rule only for a named application need, and record it beside the rule with the reason:

- Debuggers (`gdb`, `strace`) need `ptrace`; profilers need `perf_event_open`.
- Bluetooth or CAN tools need their socket families.
- Applications with their own namespace sandbox (Chromium, Electron, Flatpak, nested bwrap) need `unshare`/`clone` namespace flags and user namespaces; without them they run unsandboxed internally (`--no-sandbox`), which is a trade-off to record, not a free fix.
- Never relax the TIOCSTI/TIOCLINUX rules while the host terminal is shared.

## Testing

Test the loaded filter from inside the sandbox with the probe script's `seccomp-active`, `tty-ioctl-blocked` and `syscall-denied` checks ([verification.md](verification.md)).
`Seccomp: 2` in `/proc/self/status` only shows that some filter is loaded; the per-syscall checks call each syscall with arguments that fail harmlessly with a known errno when unfiltered (`EBADF`, `EFAULT`, `ESRCH`), so a filter-produced errno is distinguishable from the kernel's own, following bubblewrap's `tests/try-syscall.c`.
