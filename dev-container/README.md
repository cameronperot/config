# Dev Container

`dev:latest` is a Debian image for running LLM coding agents against a repository with a bounded view of the host: a container sees the repository, the agent dotfiles and the host's isolated ssh-agent, and the agents themselves run inside a bubblewrap sandbox. A container alone is not a security boundary; `c -k` adds one by booting it in a microVM (see [Isolation](#isolation)).

| File | Purpose |
| :--- | :--- |
| `Containerfile` | Image: Debian 13, user `user` (`/home/user`), micromamba env `dev`, uv, the coding agents, dotfiles via `install.py` |
| `build.sh` | Builds the image from the repository root with the builder's UID/GID and `GIT_SIGNING_KEY` |
| `compose.yml` | Long-running JupyterLab container `dev_container` |
| `entrypoint.sh` | Execs the command; under `--runtime=krun` first drops from guest root to the image user, disables TIOCSTI and bridges the TCP signer to `SSH_AUTH_SOCK` |
| `jupyter_server_config.py` | JupyterLab settings baked into the image (root `/work`, token `dev`) |

## Build
```bash
GIT_SIGNING_KEY="$(cat ~/.ssh/llm_agent_ed25519.pub)" ./dev-container/build.sh   # or: make container-build
```
- The build context is the repository root, filtered by `.containerignore`. `GIT_SIGNING_KEY` (see [Commit Signing](#commit-signing)) is written into the image's git config.
- The image user takes the builder's UID/GID and containers run with `--userns keep-id`, so each host user builds their own image and rebuilds after a UID change.

## Run
| Command | Effect |
| :--- | :--- |
| `c CMD` | Throwaway container from `dev:latest`, started in the current directory |
| `c -r CMD` | Exec in the running container whose bind mount contains the current directory (`dev_container` preferred) |
| `c -k CMD` | Like `c CMD`, inside a libkrun microVM via `--runtime=krun` (see [Isolation](#isolation)) |
| `podman-compose -f compose.yml up` | JupyterLab at `http://127.0.0.1:8888/?token=dev`, Plannotator on port 8889 |

`c` lives in `dotfiles/bin` and is deployed to `~/bin` on the host; `c --help` lists the remaining flags: `-c NAME` to pick the running container, `--cpus`/`--ram-mib` for podman resource limits (or the microVM size under `-k`), `--plannotator-port PORT`/`--no-plannotator-port` for the Plannotator UI port, `--no-git-signing` to run without commit signing, `--no-git-root`/`--ngr` to mount only the current directory instead of the git root, `-a=ARG` for extra `podman run` arguments, and `--dry-run`. A throwaway container gets:
- the repository root bind-mounted at its host path and used as the working directory; for a `.bare` layout that is the directory holding `.bare`, so every worktree resolves, and outside git it is the current directory (with `--no-git-root` only the current directory is mounted)
- `$AGENT_CONFIG_DIR/{.agent,.pi/agent,.omp/agent,.plannotator}` at the same paths under `/home/user` (`AGENT_CONFIG_DIR` must be set)
- the isolated ssh-agent as `SSH_AUTH_SOCK`: socket bind-mount, or under `c -k` a TCP bridge to the host signer (see [Isolation](#isolation) and [Signing under `c -k`](#signing-under-c--k-pasta-bridge)); when the host socket is absent, `c` warns and starts the container without it, and signing fails at commit time unless `--no-git-signing`/`GIT_SIGNING_DISABLED` is used
- a port for the Plannotator plan UI: a free loopback port is published one-to-one (`--plannotator-port PORT` to pin it, `--no-plannotator-port` to opt out), with `PLANNOTATOR_REMOTE=1` and `PLANNOTATOR_PORT` set inside
- no API-key environment variables

`compose.yml` mounts its own directory at `/work`, Jupyter's root. Keep machine-specific additions such as project mounts or the signing socket in a second compose file passed with another `-f`.

## Isolation
Three layers, each bounding what the previous one leaves open.

| Layer | Runs | Bounds |
| :--- | :--- | :--- |
| Container | `c`, `c -r`, compose | What the host exposes to the container |
| Agent sandbox | agent processes | What an agent can see and write inside the container |
| microVM | `c -k` | The kernel the container runs on |

### Container
Only the repository, the agent dotfiles and the signing socket are mounted, and no API keys are forwarded. The container shares the host kernel, so on its own it is not a security boundary.

### Agent sandbox
`agent-sandbox` (bubblewrap) wraps each agent process in a restricted view of the container, so an agent sees only its workspace and its own configuration — not unrelated repositories or other agents' state:

- **Read-only:** the system tree, and most of `$HOME`; only an allowlisted set of config files is visible, screened for credentials.
- **Writable:** only the workspace (the git toplevel, or the directory holding `.bare`) and the agent's own state directories; everything else in `$HOME`, `/tmp` and `/run` is ephemeral tmpfs.
- **Hardened:** the environment is reduced to an allowlist, IPC/UTS/PID/user namespaces are unshared, and the sandbox refuses to start while the TIOCSTI terminal-injection escape is open.
- **Limits:** credentials in the exposed config files remain readable, the package-config screen has known gaps, and the network stays shared because bubblewrap cannot filter it (LLM API egress must work).

### microVM
`c -k` boots the container on its own guest kernel (libkrun), so a kernel exploit or container escape stays inside the VM instead of reaching the host. Unix-domain sockets cannot cross the shared filesystem, so the ssh-agent is bridged over TCP (see [Signing under `c -k`](#signing-under-c--k-pasta-bridge)); `c` probes the bridge before booting and warns when no signer answers. The bridge is unauthenticated — any local host user can request signatures while it runs — so use it only on a single-user machine.

## Agents
`pi`, `omp` and `opencode` resolve to shadows in `~/bin` that launch the real binary through `agent-sandbox` (the bubblewrap layer above) from every entry point: `c`, `c -r`, zsh, bash. Escape hatches: `AGENT_SANDBOX_DISABLE=1 pi …` runs one invocation unsandboxed, `AGENT_SANDBOX_BIN=<path> pi …` launches that executable in place of the table entry, and an absolute path bypasses the shadow.

If the agent fails with an error like `bwrap: open /proc/2/ns/ns failed: No such file or directory`, bubblewrap cannot cope with the container process being PID 1: pass `c -a=--init CMD` so podman injects an init process instead (see the `-a=ARG` flag under [Run](#run)).

## Commit Signing
Commits made inside a container are signed with a dedicated SSH key that never enters the container: an isolated ssh-agent on the host holds it and only its socket is mounted (under `c -k` the agent is reached over TCP instead, see [Signing under `c -k`](#signing-under-c--k-pasta-bridge)). `dotfiles/.gitconfig` turns on SSH signing; the image build sets `user.signingkey` and `~/.ssh/allowed_signers` from `GIT_SIGNING_KEY`.

### 1. Generate the key (host)
```zsh
ssh-keygen -t ed25519 -f ~/.ssh/llm_agent_ed25519 -C "llm-agent" -N ""
```

### 2. Register it on GitHub (host)
1. `cat ~/.ssh/llm_agent_ed25519.pub`
2. GitHub → Settings → SSH and GPG keys → New SSH key, **Key type: Signing Key**, paste.

### 3. Run an isolated ssh-agent (host)
Create `~/.config/systemd/user/llm-ssh-agent.service`:
```ini
[Unit]
Description=Isolated SSH Agent for LLM Coding Agent
After=network.target

[Service]
Type=simple
Environment=SSH_AUTH_SOCK=%t/llm-agent.sock
ExecStartPre=/usr/bin/rm -f %t/llm-agent.sock
ExecStart=/usr/bin/ssh-agent -D -a %t/llm-agent.sock
ExecStartPost=/usr/bin/sh -c 'for i in $(seq 1 50); do [ -S "$SSH_AUTH_SOCK" ] && break; sleep 0.05; done; ssh-add %h/.ssh/llm_agent_ed25519'
Restart=on-failure

[Install]
WantedBy=default.target
```
```zsh
systemctl --user daemon-reload
systemctl --user enable --now llm-ssh-agent.service
```

### 4. Build and run with the key
Build with `GIT_SIGNING_KEY` as in [Build](#build). `c` mounts the socket automatically, and `c -k` bridges the agent over TCP (see [Signing under `c -k`](#signing-under-c--k-pasta-bridge)); for a plain `podman run` or a compose override add:
```zsh
-v "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/llm-agent.sock:/tmp/ssh-agent.sock" \
-e SSH_AUTH_SOCK=/tmp/ssh-agent.sock \
```

To skip signing entirely, pass `--no-git-signing` or set `GIT_SIGNING_DISABLED=1`: no agent is mounted (and under `c -k` the signer probe is skipped), no warning is printed even when the signer is missing (`c` passes `GIT_SIGNING_DISABLED=1` into the container, so `agent-sandbox` stays quiet too), and `c` injects `commit.gpgsign=false` so commits succeed unsigned.

### 5. Verify (container)
```bash
git commit --allow-empty -m "test: verify signature"
git log --show-signature -1
```
Expected: `Good "git" signature for <your GitHub email> with ED25519 key SHA256:...`

### Signing under `c -k` (pasta bridge)
virtio-fs cannot carry the socket into the microVM, but TSI does proxy the guest's TCP connections into the container's network namespace, and pasta can forward a port from there to the host's loopback. `c -k` adds `--network=pasta:-T,7777` automatically and the image's entrypoint bridges `127.0.0.1:7777` to `SSH_AUTH_SOCK`, so signing works unchanged once the host-side bridge below is running. Before booting, `c -k` probes `127.0.0.1:7777` with an ssh-agent identity request and warns when no signer answers. The ssh-agent protocol has no authentication: while the bridge runs, any local user on the host can request signatures over `127.0.0.1:7777`, so only use it on a single-user machine.

1. Host: expose the agent on loopback with a systemd user unit `~/.config/systemd/user/llm-ssh-agent-tcp.service` (`socat` required):
```ini
[Unit]
Description=TCP bridge to the isolated LLM ssh-agent
Requires=llm-ssh-agent.service
After=llm-ssh-agent.service

[Service]
ExecStart=/usr/bin/socat TCP-LISTEN:7777,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:%t/llm-agent.sock
Restart=on-failure

[Install]
WantedBy=default.target
```
```zsh
systemctl --user daemon-reload
systemctl --user enable --now llm-ssh-agent-tcp.service
```

`ssh-add -l` in the container must list the signing key; then verify as in step 5. `agent-sandbox` forwards the socket only when `gpg.format` is `ssh` and the agent holds exactly one key, the configured `user.signingkey`; the isolated agent holds exactly that key, so it passes. The sandbox identity probe has a three-second deadline and a one-second grace period before forced termination. If the bridge stalls or the probe otherwise fails, the sandbox warns and starts without forwarding the socket.
