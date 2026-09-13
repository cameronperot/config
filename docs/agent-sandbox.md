# Agent sandbox

[`dotfiles/bin/agent-sandbox`](../dotfiles/bin/agent-sandbox) launches `pi`, `omp`, `opencode`, or `claude` with filesystem isolation provided by `unshare` and Bubblewrap. The wrapper uses Python's standard library and replaces itself with the launch command. In this document, “host” means the environment invoking the wrapper, which can itself be a [dev container](../dev-container/README.md#isolation).

## Requirements

- Linux with working user, PID, IPC, UTS, and mount namespaces.
- Python 3.12+, `unshare`, `bwrap`, `git`, and `ssh-add`.
- `/proc/sys/dev/tty/legacy_tiocsti` present and set to `0`; the wrapper refuses to launch if the terminal-injection protection is unavailable or disabled.
- The runtime trees `/usr`, `/etc`, and `/opt/mamba`, plus an existing `$HOME/.gitconfig`; these are mandatory read-only mounts.
- A canonical, absolute `$HOME`, without symlinked components, redundant components, or a trailing slash, and not `/`.
- An executable agent at `$HOME/.local/bin/<agent>`, or an override through `AGENT_SANDBOX_BIN` whose resolved target is visible inside the sandbox.

The dev-container image supplies the expected runtime layout. [`install.py`](../install.py) deploys the wrapper to `~/bin`; the image also creates `pi`, `omp`, and `opencode` links to [`agent-shadow`](../dotfiles/bin/agent-shadow), which routes those commands through the sandbox.

## Usage

Run from inside the project the agent should edit:

```bash
agent-sandbox pi
```

The syntax is `agent-sandbox [script-flags] [--] <agent> [agent-args...]`. Wrapper flags must precede the agent name; every argument after it goes to the agent verbatim.

| Wrapper flag | Effect |
| :--- | :--- |
| `-h`, `--help` | Print help and exit |
| `-v`, `--verbose` | Report workspace resolution, signing, namespace capability, and environment forwarding on stderr |
| `--debug` | Enable verbose output plus two diagnostic lines: a resolution summary and the redacted launch argument vector; not a line-by-line trace |
| `--dry-run` | Print a shell-quoted launch command without creating state or launching the sandbox |

Diagnostics and dry-run output redact values from the five API-key variables listed below. This is not general-purpose secret redaction: credentials in other variables or agent arguments can appear in output. A dry run still validates paths and terminal protection, queries Git, screens package configuration, and may query the SSH agent. It skips the namespace capability probe, so its output does not include the conditional `--disable-userns` flags used by a supported real launch.

## Workspace and filesystem access

| Location | Access and lifetime |
| :--- | :--- |
| Git toplevel, or current directory outside Git | Read-write host bind; edits persist |
| External Git common directory for a linked worktree | Separate read-write host bind; Git metadata changes persist |
| Directory containing a Git common directory named `.bare` | Entire directory becomes the writable workspace, including sibling worktrees |
| Ancestors of the writable binds, excluding `$HOME` and `/` | Empty overlays remounted read-only; unrelated host contents are hidden |
| `/usr`, `/etc`, `/opt/mamba` | Read-only host binds |
| `/bin`, `/sbin`, `/lib`, `/lib64` | Links into `/usr` |
| `$HOME`, `/tmp`, `/run` | Fresh, writable tmpfs; contents are ephemeral except for explicit host binds |
| `/proc`, `/dev` | Fresh process and device mounts |

The agent starts in the original working directory. The wrapper rejects writable roots at `/`, `$HOME`, ancestors of `$HOME`, or beneath a top-level hidden entry in `$HOME`. It also rejects roots at or beneath `/usr`, `/bin`, `/sbin`, `/lib`, `/lib64`, `/etc`, `/opt`, `/var`, `/boot`, `/root`, `/srv`, `/tmp`, `/run`, `/proc`, `/sys`, and `/dev`. The same restrictions apply to an external Git common directory. A Git directory without a worktree is rejected unless its resolved name is `.bare`.

Ordinary linked worktrees expose shared Git metadata but hide sibling worktree contents. Manage worktrees from the host; the `.bare` layout is the exception because the entire containing directory is writable and visible.

The following home paths are exposed read-only when present:

- `.config/git/config`, `.config/git/ignore`, `.config/git/attributes`.
- `.config/pip`, `.config/pnpm`, `.config/uv`.
- `.local/bin`, `.local/lib`, `.local/share/claude`, `.local/share/pnpm`, `.local/share/uv`.
- `.ssh/allowed_signers`, plus an accepted SSH signing public-key file.
- `.npmrc` and `.bunfig.toml`, only after credential screening.

`.gitconfig` is a required read-only bind. Only `.npmrc` and `.bunfig.toml` receive the package credential scan: files are omitted with a warning if unreadable or if any line matches `_auth`, `token`, `password`, `username`, or a URL containing user information before `@`, case-insensitively. The scan includes comments and does not parse TOML or decode escapes; it can reject harmless text and miss encoded secrets. Other exposed configuration, state, and workspace files are not screened for secrets.

## Persistent state and protected configuration

All paths in this table are relative to `$HOME`. Each agent also receives writable `.agent` state, with `.agent/skills`, `.agent/prompts`, and `.agent/rules` pinned read-only. That shared state is visible across agents.

| Agent | Additional writable state | Additional read-only pins |
| :--- | :--- | :--- |
| `pi` | `.pi` | Under `.pi/agent/`: `skills`, `prompts`, `settings.json`, `guard-rules.json`, `AGENTS.md`, `agents`, `extensions` |
| `omp` | `.omp` | Under `.omp/agent/`: `skills`, `prompts`, `config.yml`, `AGENTS.md`, `extensions` |
| `opencode` | `.opencode`, `.local/share/opencode`, `.local/state/opencode`, `.local/share/opentui` | Entire `.config/opencode` directory |
| `claude` | `.claude`, `.local/state/claude` | Under `.claude/`: `settings.json`, `skills`, `rules`, `agents`, `commands` |

Before a real launch, the wrapper creates missing state directories on the host and verifies that they are owned by the invoking user and have no symlinked components. Pinned symlinks must resolve within the selected agent's state directories. Missing pinned JSON files are seeded with `{}`, and missing pinned directory paths are created; absent `AGENTS.md` and `config.yml` files are not seeded. Existing pins are mounted read-only over the writable state.

Edit protected configuration and install OpenCode plugins from the host. `pi-create-skill` and `pi-create-prompt` target pinned paths and therefore need to run on the host. Other writes beneath the sandbox's `.local` and `.config` disappear on exit unless covered by a persistent bind.

For Claude, the wrapper sets `CLAUDE_CONFIG_DIR=$HOME/.claude`. If `$HOME/.claude/.claude.json` is absent and `$HOME/.claude.json` exists, it copies the latter once before launching, using the source permissions restricted by the process umask. Host and sandbox Claude state then diverge unless the host also uses the same `CLAUDE_CONFIG_DIR`.

## Environment and overrides

The sandbox clears the inherited environment and supplies `HOME`, `PWD`, `USER`, `LOGNAME`, `SHELL=/bin/bash`, and `XDG_RUNTIME_DIR=/run/user/<UID>`. Its fixed `PATH` is `/opt/mamba/envs/dev/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin`. The host's `PATH` and shell startup configuration are not forwarded.

| Variables | Forwarding rule |
| :--- | :--- |
| `TERM`, `COLORTERM`, `LANG`, `LC_ALL`, `LC_CTYPE`, `LC_MESSAGES`, `LC_COLLATE`, `LC_NUMERIC`, `LC_TIME`, `TZ` | Nonempty values; `TERM` defaults to `dumb` when unset |
| `http_proxy`, `https_proxy`, `no_proxy`, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` | Nonempty values |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OPENCODE_API_KEY`, `GEMINI_API_KEY` | Nonempty values; readable by the agent but redacted from wrapper diagnostics |
| `TERMINFO`, `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` | Resolved canonical paths only when existing and within an exposed tree; otherwise omitted with a warning |
| `PLANNOTATOR_PORT`, `PLANNOTATOR_REMOTE` | Forwarded only when the host sets a nonempty port; remote defaults to `1` |
| `SSH_AUTH_SOCK` | Only after the signing checks below |

| Override | Behavior |
| :--- | :--- |
| `AGENT_SANDBOX_BIN=<path>` | Select a different executable; the agent name still determines the state policy |
| `AGENT_SANDBOX_DISABLE=1` | Execute the agent directly without sandbox setup |
| `AGENT_SANDBOX_ACTIVE` | Set to `1` inside the sandbox; an existing nonempty value causes direct execution to prevent nesting |
| `GIT_SIGNING_DISABLED=1` | Suppress the warning for an unset `SSH_AUTH_SOCK`; does not disable forwarding of a supplied socket |

Both bypass variables are tested for nonempty values, so even `AGENT_SANDBOX_DISABLE=0` bypasses isolation. Bypass handling precedes dry-run handling: with either bypass variable set, `--dry-run` still executes the agent directly.

## Git signing and GitHub access

The wrapper selects the signing identity from global Git configuration, ignoring repository-local overrides:

1. Require `gpg.format=ssh` and a nonempty `user.signingkey`.
2. Accept an inline public key, optionally prefixed with `key::`, or a public-key file whose first line has a recognized SSH key type and which has exactly one nonblank line.
3. Resolve `SSH_AUTH_SOCK` and require a Unix socket owned by the invoking user.
4. Query `ssh-add -L` with a three-second timeout and a one-second termination grace period.
5. Forward the socket only if it reports exactly one identity matching the configured key's type and blob.

Rejected sockets produce a warning and are omitted; the agent can still launch. The identity check happens only at launch and does not filter later socket requests or prevent identities being added afterward. Use a dedicated signing agent; see [SSH setup](ssh.md#container-signing-agent) and [container commit signing](../dev-container/README.md#commit-signing).

The wrapper does not forward `GH_TOKEN`, `GITHUB_TOKEN`, or `~/.config/gh`. Run authenticated GitHub operations and pushes on the host using its credentials. Credentials placed in other exposed files remain available inside the sandbox.

## Isolation limits and troubleshooting

The sandbox shares the network and the invoking environment's kernel. It isolates user, PID, IPC, UTS, and mount namespaces and enables Bubblewrap's `--die-with-parent` behavior. For `pi`, `omp`, and `opencode`, a capability probe enables blocking of nested user namespaces when supported; a failed probe warns and leaves nesting possible. Claude leaves nested user namespaces available. Filesystem isolation does not protect secrets in exposed files or forwarded API keys from the agent.

| Symptom | Action |
| :--- | :--- |
| `agent executable missing or not executable` | Check `$HOME/.local/bin/<agent>` or supply `AGENT_SANDBOX_BIN` |
| Executable resolves outside exposed paths | Install it in an exposed toolchain directory or select a visible executable |
| `HOME is not canonical` | Set `$HOME` to its physical absolute path without a trailing slash |
| `HOME is /` | Set `$HOME` to a real home directory |
| `TIOCSTI escape unmitigated` | Have the host provide `/proc/sys/dev/tty/legacy_tiocsti` with value `0` |
| Workspace bind refused | Launch from a project directory outside the denied locations |
| State ownership or symlink error | Correct the named host state path; pinned symlinks must stay within the selected state trees |
| Protected settings or plugin installation fails | Edit or install from the host |
| SSH agent not forwarded | Check global signing configuration, socket ownership, and the socket's identity list |
| `bwrap: open /proc/2/ns/ns failed: No such file or directory` in the dev container | Use `c -a=--init CMD` so Podman supplies an init process |

Help and successful dry runs return `0`; wrapper validation and filesystem errors normally return `1`. Process replacement failures return `127` for a missing executable or `126` for other execution errors. After successful replacement, the launched process determines the exit status.

The existing test suite is [`tests/test_agent_sandbox.py`](../tests/test_agent_sandbox.py), runnable with `uv run pytest -q tests/test_agent_sandbox.py`. Its real-sandbox smoke test explicitly skips when namespace tools, the required runtime tree, or host namespace/mount capabilities are unavailable.
