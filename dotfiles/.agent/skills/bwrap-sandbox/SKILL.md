---
name: bwrap-sandbox
description: Designs and writes Bubblewrap (bwrap) launcher scripts that confine an application with a risk-tiered filesystem, namespace, network, terminal and seccomp policy, in Bash or Python by complexity, and verifies isolation with a bundled in-sandbox probe script. Use when asked to sandbox, isolate, jail or confine an application or command, to run something without access to the home directory, other projects or the network, to write, review, harden or debug a bwrap or bubblewrap launcher, or whenever bwrap or bubblewrap comes up.
disable-model-invocation: true
---

# bwrap-sandbox

Produce a launcher whose every exposure is deliberate, written down and tested: bwrap is a toolkit, not a policy, so the script that builds its arguments owns the security model.

Trailing input after `/skill:bwrap-sandbox` names the application to sandbox and its requirements, or an existing launcher to review; with no input, derive both from the conversation and ask for anything missing in one consolidated question.

## Hard rules

- Call bwrap and every other host-side executable by absolute path, never through `PATH`, which can include project directories the sandbox writes (an activated `.venv/bin`). A Bash launcher therefore uses `#!/bin/bash` instead of `bash-conventions`' `#!/usr/bin/env bash` and resets `PATH` before running any utility.
- Resolve every path the policy derives from the environment (`$HOME`, the working directory, user arguments) to its physical form before checking or binding it; bwrap resolves bind sources itself, so a symlinked alias would otherwise pass a lexical check.
- Close every inherited descriptor above 2 before `exec`ing bwrap, unless the access table grants it; bwrap passes extra descriptors to the command, where a writable file or connected socket bypasses the mount and network policy.
- Require bwrap 0.12.0 or later and check every option the launcher uses against that binary's `--help`; fail when either check fails. Releases before 0.12.0 let sandbox content redirect setup writes onto the host through symlinks, and the man page omits some options that `--help` lists.
- End bwrap's options with `--`, and keep wrapper flags, user input and application arguments out of bwrap's option positions.
- Fail closed: when a protection cannot be set up, exit non-zero before the application starts. Never fall back to an unsandboxed run, never pass `--not-a-security-boundary`, never install or rely on a setuid bwrap. Add a bypass only when the user asks for one, and make it announce itself on stderr.
- Pass `--cap-drop ALL`: bwrap keeps capabilities when it runs as uid 0, which is the case inside pasta's or rootless Podman's user namespace.
- Pair a PID namespace with `--proc /proc`; without bwrap's own PID namespace, `--proc` binds the outer `/proc` and every outer process stays visible.
- Pass `--clearenv` and set an explicit allowlist. Forward secrets only through `--args FD`, never as `--setenv` on the visible command line, and redact them in `--dry-run` and debug output.
- Follow the terminal rule in [references/integrations.md](references/integrations.md#terminal-policy): `--new-session` by default; an application that keeps the host terminal needs the masked TIOCSTI/TIOCLINUX seccomp filter in every tier.
- Never bind `/`, `$HOME`, `/run/user/<uid>`, `/dev`, `/sys`, a D-Bus or X11 socket, a container-engine socket or an SSH or GPG agent socket wholesale to make startup succeed. Out-of-scope integrations (X11, D-Bus, audio, portals) are reported to the user, not improvised.
- Do not disable an application's own sandbox (for example Electron's `--no-sandbox`) as a casual fix; when the policy forces it, record it as a trade-off in the residual risks.
- Do not install packages, change sysctls or edit AppArmor or SELinux policy; give the user the command.

## Workflow

1. **Threat and tier.** Establish what is trusted and what is not, and pick the risk tier below; state it in one line.
2. **Inventory.** List what the application needs: binaries and libraries, configuration read, state written, network directions (outbound, inbound, host loopback, DNS), sockets, devices, terminal behaviour, subprocesses, and any sandbox of its own. When the needs are unknown, start from a restrictive policy and widen it from the failures. To trace, run `--exec -- /usr/bin/strace -f …` under a diagnostic variant of the policy that differs only by allowing `ptrace` in the seccomp filter, keeping every filesystem, namespace, network and terminal boundary. Trace on the host only a trusted application, never hostile code, which a host trace runs unconfined.
3. **Access table.** Write one row per resource: host source, sandbox path, access (`ro`, `rw`, `dev`, `tmpfs`, socket), persistence, reason. Every bwrap mount and every forwarded variable traces to a row.
4. **Policy.** Choose the filesystem layout, namespaces, network mode, terminal handling, seccomp filter and integrations from the references, meeting at least the tier's minimum.
5. **Language.** Apply the rule below, read `bash-conventions` or `py-conventions`, and start from the matching asset.
6. **Build and inspect.** Write the launcher, run `--dry-run`, and compare the printed argv with the access table line by line: order, `--` placement, redaction, nothing extra.
7. **Verify.** Lint and unit-test where you are; run the probe script and the application on the host per [references/verification.md](references/verification.md). In a dev container without bwrap, hand the user the exact host commands.
8. **Report.** List the protections verified on the host, the exposures granted on purpose, and every check not run, labelled unverified; never report an unrun check as passed.

## Risk tiers

Each tier includes everything in the tiers above it; exceed the minimum when the inventory allows it, never go below it.

| Tier | When | Minimum protections |
|---|---|---|
| Accidental damage | Trusted application; guard against bugs and mistakes | Filesystem limited to the access table, tmpfs `$HOME`, `--clearenv` allowlist, PID namespace with `--proc`, `--die-with-parent`, `--cap-drop ALL` |
| Compromised application | Trusted application with untrusted plugins, extensions, dependencies or updates | `--unshare-user --disable-userns`, `--new-session` or the terminal rule, network `none` or `pasta`, no D-Bus, persistent state only in a dedicated store, host-executed configuration pinned read-only |
| Hostile code | Untrusted binaries, scripts or input | Seccomp baseline from [references/seccomp.md](references/seccomp.md) including io_uring, network `none` unless justified in the access table, no persistent state unless justified |

The seccomp filter is otherwise a per-application choice: add it to the lower tiers when the threat warrants it, and always for the terminal rule.

## Bash or Python

Write Bash only when all of these hold; otherwise write Python:

- The policy is fixed: no user-supplied writable paths that need overlap or ancestor validation.
- No seccomp filter is needed; building BPF requires the libseccomp Python bindings.
- No Wayland security context.
- No helper process to supervise; a `pasta … -- <stage> bwrap …` prefix the launcher `exec`s does not count.
- The script stays within about 100 lines.

## Launcher requirements

Every launcher, in either language, has:

- `-h`/`--help`, and `--dry-run` printing the full redacted argv without creating state or launching.
- `--exec -- CMD [ARGS]`, which runs `CMD` instead of the application under the identical policy; the probe script runs through it.
- A preflight that resolves each external tool to its absolute path, checks the bwrap version and option tokens, and checks every host prerequisite the policy relies on, failing with an actionable message.
- The access table and a residual-risks list, in the documentation location the repository's `AGENTS.md` names, or else in the launcher's header comment.

## References

| File | Read when |
|---|---|
| [references/bwrap-semantics.md](references/bwrap-semantics.md) | Always: option ordering, namespaces, capabilities, confusable options, version and feature detection |
| [references/filesystem.md](references/filesystem.md) | Always: baseline layout, `/etc`, home and persistent state, writable-root validation, host-executed files, symlink swaps |
| [references/integrations.md](references/integrations.md) | Network access, an interactive terminal, Wayland or GPU, a helper process, or forwarded secrets |
| [references/seccomp.md](references/seccomp.md) | The tier or the terminal rule requires a filter, or the user asks for syscall filtering |
| [references/verification.md](references/verification.md) | Step 7, and when bwrap fails with a namespace, mount or permission error |

## Assets and scripts

- [assets/example-cli.sh](assets/example-cli.sh): Bash, accidental-damage tier, offline CLI tool reading the working directory. Adapt it; do not copy it unexamined.
- [assets/example-interactive.py](assets/example-interactive.py): Python, compromised-application tier, interactive terminal application with pasta networking, the masked seccomp filter, secrets through `--args` and writable-root validation. Adapt it; do not copy it unexamined.
- [scripts/probe.py](scripts/probe.py): run it inside the generated sandbox through `--exec` to test isolation properties; `python3 scripts/probe.py --help` lists the checks, and [references/verification.md](references/verification.md) gives the host procedure.
