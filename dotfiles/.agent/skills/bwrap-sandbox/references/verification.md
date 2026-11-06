# Verification

Contents: [Principles](#principles) · [Where each check runs](#where-each-check-runs) · [Unit tests](#unit-tests) · [Host fixtures](#host-fixtures) · [Running the probe](#running-the-probe) · [Checks by tier](#checks-by-tier) · [Interpreting results](#interpreting-results) · [Application acceptance](#application-acceptance) · [Probe test suites](#probe-test-suites) · [Troubleshooting](#troubleshooting)

## Principles

- Verify individual properties (this file is hidden, this path is read-only, host processes are invisible), never "the sandbox is secure".
- A check that did not run is unverified, not passed; a check that ends in `error` is unverified too.
- Use synthetic sentinels, never real secrets, and never inject into the user's own terminal or signal the user's own process group.
- Test the production policy: do not widen the launcher's mounts to make the probe work and then report the narrower policy as tested.

## Where each check runs

| Check | Dev container (no bwrap) | Host |
|---|---|---|
| `bash -n`, shellcheck, shfmt, or ruff and ty | Yes | Yes |
| Unit tests with bwrap stubbed | Yes | Yes |
| `--dry-run` argv review against the access table | Yes | Yes |
| Probe script inside the real sandbox | No | Yes |
| Application acceptance | No | Yes |

In the dev container, give the user the exact host commands for the last two rows and report them as unverified until the user returns the output.
Do not install bwrap, change sysctls or weaken the launcher to make anything run in the container.

## Unit tests

For Python launchers, and Bash launchers when the repository tests its scripts, test without bwrap by replacing the executables with stubs that record their argv:

- Option order: system trees before writable roots, read-only pins after the writable areas they sit in, `--` immediately before the command.
- Every path in the argv is absolute and non-empty; the command's arguments appear only after `--`.
- The environment allowlist: nothing outside it reaches `--setenv` or the inherited environment.
- Writable-root validation rejects each forbidden class from [filesystem.md](filesystem.md#writable-roots), in lexical and resolved form.
- Preflight fails closed: missing bwrap, version below 0.12.0, missing option token, missing seccomp bindings, `legacy_tiocsti` not 0 when required.
- Secrets never appear in the argv or the `--dry-run` output.

`tests/test_vscode_sandbox.py` and `tests/test_agent_sandbox.py` in the dotfiles repository show the stub pattern; stubs prove argument construction, not kernel enforcement.

## Host fixtures

Create these on the host before running the probe, with a unique token and a private directory per run:

```bash
token="bwrap-probe-$(date +%s)"
fixtures="$(mktemp -d)"
printf 'sentinel\n' >"${HOME}/.${token}"
mkdir "${fixtures}/ro" && touch "${fixtures}/ro/file"
bash -c "exec -a ${token} sleep 600" &
sentinel_pid=$!
python3 -m http.server --bind 127.0.0.1 0 >"${fixtures}/http.log" 2>&1 &
listener_pid=$!
until port="$(ss -Hltnp | grep -F "pid=${listener_pid}," | grep -oP '127\.0\.0\.1:\K[0-9]+')"; do
    sleep 0.2
done
(exec 3<>"/dev/tcp/127.0.0.1/${port}") && echo "listener ready on ${port}"
```

- The hidden-file sentinel sits directly in `$HOME`, outside every bind.
- The read-only fixture must be writable by the user on the host and bound read-only by the policy under test; skip it when the policy has no read-only bind of a user-writable path, and use a real read-only bind (`/usr`) instead.
- The sentinel process's `argv[0]` is the token; `pid-hidden` matches `argv[0]` exactly, so bwrap's own command line, which contains `pid-hidden:TOKEN`, does not count.
- The listener on host loopback tests that `none` and `pasta` keep host loopback unreachable. Repeat the outside connection after the probe as well, so a dead listener cannot produce a false pass.
- For `pasta`, also test `connect-blocked:[::1]:PORT` and `connect-blocked:<gateway>:PORT`, where `<gateway>` is the default route inside the sandbox (`ip route` through `--exec`); the gateway check is what catches a missing `--no-map-gw`. Use a second listener and `-T` for a forwarded-port positive control.
- For inherited descriptors, launch with deliberate extras (`9>"${fixtures}/fd-file" 8<>"/dev/tcp/127.0.0.1/${port}"`) and expect `fds-only:0,1,2`; a launch with only stdio does not test the boundary.

Clean up afterwards: `kill "${sentinel_pid}" "${listener_pid}"; rm -rf "${HOME}/.${token}" "${fixtures}"`.

## Running the probe

Feed the probe on standard input so it needs no bind of its own:

```bash
launcher --exec -- /usr/bin/python3 -I - \
    "hidden:${HOME}/.${token}" readonly:/usr "pid-hidden:${token}" \
    userns-blocked "connect-blocked:127.0.0.1:${port}" fds-only:0,1,2 \
    seccomp-active tty-ioctl-blocked syscall-denied:ptrace \
    syscall-denied:clone3:ENOSYS <scripts/probe.py
```

- `python3 scripts/probe.py --help` lists every check and its argument form.
- The probe validates every argument before running anything, then prints one JSON object per check as it completes, with `check`, `arg`, `result` (`pass`, `fail`, `error`, `not-applicable`), `expected` and `observed`; it exits 0 only when every result is `pass` or `not-applicable`.
- When the launcher redirects stdin, copy the probe into a path the policy already exposes read-only and run it from there.
- Launchers whose policy has no `/usr/bin/python3` (a curated runtime without Python) need the checks run with the shell tools the runtime has; report the unrunnable checks as unverified.

## Checks by tier

| Check | Accidental | Compromised | Hostile | Proves |
|---|---|---|---|---|
| `hidden:PATH` | Yes | Yes | Yes | `PATH` does not exist inside (ENOENT) |
| `readonly:PATH` | Yes | Yes | Yes | Creating or writing fails with EROFS, not just EACCES |
| `writable:PATH` | Yes | Yes | Yes | Positive control: a granted writable path accepts writes |
| `pid-hidden:TOKEN` | Yes | Yes | Yes | No visible process has `argv[0]` equal to `TOKEN`, and `/proc` works |
| `fds-only:LIST` | Yes | Yes | Yes | Only the listed descriptors are inherited |
| `userns-blocked` | — | Yes | Yes | Creating a user namespace fails |
| `connect-blocked:HOST:PORT` | Network `none`/`pasta` | Yes | Yes | The address is unreachable; use IP literals, since DNS and local resource failures report `error` |
| `connect-allowed:HOST:PORT` | When granted | When granted | When granted | Positive control for granted connectivity |
| `pgrp-isolated` | With `--new-session` | With `--new-session` | With `--new-session` | The sandbox's process group and session were allocated inside its PID namespace; under the shared-terminal rule it fails by design, so skip it there and keep the residual risk listed |
| `seccomp-active` | When filtered | When filtered | Yes | A seccomp filter is loaded |
| `tty-ioctl-blocked` | Shared terminal | Shared terminal | Yes | TIOCSTI, TIOCLINUX and high-bit TIOCSTI fail with EPERM instead of EBADF |
| `syscall-denied:NAME[:ERRNO]` | When filtered | When filtered | Yes | `NAME` fails with the filter's errno (default EPERM) instead of the kernel's |

`syscall-denied` supports `ptrace`, `chroot`, `add_key`, `perf_event_open`, `setns`, `personality`, `io_uring_setup` and `clone3` on x86_64 and aarch64; on other architectures it reports `error`.
An `ERRNO` equal to what the unfiltered syscall returns (for example `ptrace:ESRCH`) is rejected as a usage error, because it could not distinguish a filter from none.

## Interpreting results

- `pass`: the property held under this host's kernel, bwrap, LSM policy and launcher version; record those versions with the result.
- `fail`: the property did not hold; fix the policy, never the expectation, unless the access table grants the access deliberately.
- `error`: the check could not decide (a fixture missing, EACCES where EROFS was expected, an unsupported architecture); fix the fixture and re-run.
- `not-applicable`: the property cannot apply here (io_uring disabled for every caller by `kernel.io_uring_disabled=2`); state why in the report. With value 1 an `EPERM` could come from the sysctl, so the check reports `error`.

## Application acceptance

Run the real application through the launcher on the host and exercise what the user needs: open, edit and save in the granted paths; network features; terminal resize and job control when relevant; GPU or software rendering for GUIs.
For launchers with helpers, also kill the launcher, the helper and bwrap in turn, and check that no sandbox process, helper, lock or temporary file survives.

## Probe test suites

Write a pytest suite that drives real sandboxes, like `tests/test_vscode_sandbox_probes.py`, only for Python launchers that supervise a helper (pasta, a Wayland listener) or outlive their `exec`.
Gate it behind an environment variable so it skips everywhere except an explicit host run, import the launcher's argv builder instead of duplicating the policy, and keep host-side sentinels in the test process.

## Troubleshooting

| bwrap message or symptom | Cause | Action for the user on the host |
|---|---|---|
| `setting up uid map: Permission denied` | Ubuntu 23.10+ AppArmor restriction on unprivileged user namespaces (`kernel.apparmor_restrict_unprivileged_userns=1`) | Inspect the denial in the audit log and the distribution's bwrap AppArmor profile; do not disable the restriction globally |
| `No permissions to create a new namespace, likely because the kernel does not allow non-privileged user namespaces…` | `kernel.unprivileged_userns_clone=0` (Debian) or an LSM denial | The message names the sysctl; changing it is the user's decision |
| `Creating new namespace failed: nesting depth or /proc/sys/user/max_*_namespaces exceeded (ENOSPC)` | `user.max_user_namespaces=0`, or already inside a `--disable-userns` sandbox | Check the sysctl; do not nest the launcher inside itself |
| `setuid use of bubblewrap is not supported` | bwrap installed setuid | Reinstall the distribution package without the setuid bit |
| `Can't find source path <path>` | A required bind source is missing | Create it on the host, or use a `-try` variant only if the resource is optional |
| `Can't create file <dest>` / `Can't mkdir parents for <dest>` with `Read-only file system` | A mount point inside a read-only bind | See [filesystem.md](filesystem.md#mount-order) |
| `creation of new user namespaces was not disabled as requested` | `--disable-userns` did not take effect | Stop: the protection is missing |
| `open /proc/2/ns/ns failed: No such file or directory` inside a container | The container has no init process | Run the container with an init (`podman run --init`) |
| `execvp <command>: No such file or directory` for an existing binary | Missing `/lib64` or `/lib` link, or the interpreter of a script is not exposed | Mirror the host's top-level links |
| DNS fails inside | `/etc/resolv.conf` points into the hidden `/run`, or at systemd-resolved's unreachable stub | See [filesystem.md](filesystem.md#dns-configuration) |
