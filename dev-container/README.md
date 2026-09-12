# Dev Container

`dev:latest` is a Debian 13 image with support for various LLM coding agents. `c` mounts the repository, agent configuration, and an isolated host SSH-agent socket. Agent commands run sandboxed using bubblewrap and/or libkrun microVMs (see [Isolation](#isolation)).

| File | Purpose |
| :--- | :--- |
| `Containerfile` | Image: Debian 13, user `user` (`/home/user`), micromamba env `dev`, uv, the coding agents, dotfiles via `install.py` |
| `build.sh` | Builds the image from the repository root with the builder's UID/GID and `GIT_SIGNING_KEY` |
| `compose.yml` | Long-running JupyterLab container `dev_container` |
| `entrypoint.sh` | Execs the command; under `--runtime=krun` first drops from guest root to the image user, disables TIOCSTI and, when signing is enabled, bridges the TCP signer to `SSH_AUTH_SOCK` |
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

`c` is deployed from `dotfiles/bin` to `~/bin` on the host. Use `c --help` for all options.

| Option | Effect |
| :--- | :--- |
| `-c NAME` | Select a running container; implies `-r` |
| `--cpus`, `--ram-mib` | Set resource limits, or microVM size under `-k` |
| `--plannotator-port PORT` | Pin the Plannotator UI port |
| `--no-plannotator-port` | Disable Plannotator port publishing |
| `--no-git-signing`, `--ngs` | Disable commit signing |
| `--no-git-root`, `--ngr` | Mount only the current directory |
| `-a=ARG` | Add a `podman run` argument |
| `--dry-run` | Print the command without running it |

A throwaway container starts in the current directory and receives:

- the repository root mounted at its host path; for a `.bare` layout, the directory holding `.bare`; outside Git or with `--no-git-root`, only the current directory
- `$AGENT_CONFIG_DIR/{.agent,.pi/agent,.omp/agent,.plannotator}` at the same paths under `/home/user` (`AGENT_CONFIG_DIR` must be set)
- the isolated ssh-agent as `SSH_AUTH_SOCK`: socket bind-mount, or under `c -k` a TCP bridge to the host signer (see [Isolation](#isolation) and [Signing under `c -k`](#signing-under-c--k-pasta-bridge)); when the host socket is absent, `c` warns and starts the container without it, and signing fails at commit time unless `--no-git-signing`/`GIT_SIGNING_DISABLED` is used
- a port for the Plannotator plan UI: a free loopback port is published one-to-one (`--plannotator-port PORT` to pin it, `--no-plannotator-port` to opt out), with `PLANNOTATOR_REMOTE=1` and `PLANNOTATOR_PORT` set inside
- no API-key environment variables (use the harness' login functionality)

`compose.yml` mounts its own directory at `/work`, Jupyter's root. Keep machine-specific additions such as project mounts or the signing socket in a second compose file passed with another `-f`.

## Isolation

| Layer | Runs | Bounds |
| :--- | :--- | :--- |
| Container | `c`, `c -r`, compose | What the host exposes to the container |
| Agent sandbox | agent processes | What an agent can see and write inside the container |
| microVM | `c -k` | The kernel the container runs on |

### Container
By default, `c` mounts the repository, agent configuration, and signing socket. The container shares the host kernel.

### Agent sandbox
`agent-sandbox` uses bubblewrap to restrict each agent's filesystem access:

- **Read-only:** the system tree, and most of `$HOME`; only an allowlisted set of config files is visible, screened for credentials.
- **Writable:** only the workspace (the git toplevel, or the directory holding `.bare`) and the agent's own state directories; everything else in `$HOME`, `/tmp` and `/run` is ephemeral tmpfs.
- **Hardened:** the environment is reduced to an allowlist, IPC/UTS/PID/user namespaces are unshared, and the sandbox refuses to start while the TIOCSTI terminal-injection escape is open.
- **Limits:** credentials in the exposed config files remain readable, the package-config screen has known gaps, and the network stays shared because bubblewrap cannot filter it.

### microVM
`c -k` boots the container on a separate guest kernel through libkrun. The host signing agent is reached through a TCP bridge because Unix-domain sockets cannot cross the shared filesystem. See [Signing under `c -k`](#signing-under-c--k-pasta-bridge) for setup and access limits.

## Agents
`pi`, `omp` and `opencode` resolve to wrappers in `~/bin` that launch the real binary through `agent-sandbox`. This applies through `c`, `c -r`, Zsh and Bash.

| Override | Effect |
| :--- | :--- |
| `AGENT_SANDBOX_DISABLE=1 pi …` | Run one invocation without the sandbox |
| `AGENT_SANDBOX_BIN=<path> pi …` | Use a different agent executable |
| Absolute path to the agent binary | Bypass the wrapper |

If the agent fails with an error like `bwrap: open /proc/2/ns/ns failed: No such file or directory`, bubblewrap cannot handle the container process being PID 1: pass `c -a=--init CMD` so podman injects an init process instead.

## Commit Signing
SSH signing uses a dedicated private key held by an isolated agent on the host. Containers receive its socket, or a TCP connection under `c -k`. `dotfiles/.gitconfig` enables SSH signing; the image build sets `user.signingkey` and `~/.ssh/allowed_signers` from the public key in `GIT_SIGNING_KEY`.

### 1. Generate the key (host)
```zsh
ssh-keygen -t ed25519 -f ~/.ssh/llm_agent_ed25519 -C "llm-agent" -N ""
```

### 2. Register it on GitHub (host)
1. `cat ~/.ssh/llm_agent_ed25519.pub`
2. GitHub → Settings → SSH and GPG keys → New SSH key, **Key type: Signing Key**, paste.

### 3. Run an isolated ssh-agent (host)
Install the dotfiles on the host first; they include [llm-ssh-agent.service](../dotfiles/.config/systemd/user/llm-ssh-agent.service). The service owns `$XDG_RUNTIME_DIR/llm-agent.sock`, waits for the socket, and loads only `~/.ssh/llm_agent_ed25519`. The signing key must have no passphrase for unattended startup; failure to load it fails service startup.

```zsh
systemctl --user daemon-reload
systemctl --user enable --now llm-ssh-agent.service
```

If replacing an already-running unit, also run `systemctl --user restart llm-ssh-agent.service`. Verify the host agent with `SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/llm-agent.sock" ssh-add -l`. The personal agent is separate and is never selected by `c`; see [SSH](../docs/ssh.md) for its setup. The image sets `container=oci` so Zsh preserves the supplied socket without starting an agent or loading private keys.

### 4. Build and run with the key
Build with `GIT_SIGNING_KEY` as in [Build](#build). `c` mounts the socket automatically; `c -k` uses the [TCP bridge](#signing-under-c--k-pasta-bridge). For plain `podman run`, add these arguments; for Compose, set the equivalent volume and environment entries:
```zsh
-v "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/llm-agent.sock:/tmp/ssh-agent.sock" \
-e SSH_AUTH_SOCK=/tmp/ssh-agent.sock \
```

To disable signing, pass `c --no-git-signing`, `c --ngs`, or set `GIT_SIGNING_DISABLED=1` when launching `c`. `c` omits the host socket mount and `SSH_AUTH_SOCK`, skips the microVM signer probe, and sets `commit.gpgsign=false` and `GIT_SIGNING_DISABLED=1` inside the container. Under `c -k`, pasta networking remains enabled without the signer-port forwarding, and the entrypoint does not start the signing bridge. Commits are unsigned, and missing-signer warnings are suppressed.

### 5. Verify (container)
```bash
git commit --allow-empty -m "test: verify signature"
git log --show-signature -1
```
Expected: `Good "git" signature for <your GitHub email> with ED25519 key SHA256:...`

### Signing under `c -k` (pasta bridge)
When signing is enabled, `c -k` adds `--network=pasta:-T,7777`; the image entrypoint bridges `127.0.0.1:7777` to `SSH_AUTH_SOCK` inside the microVM, with the socket owned by the container user so `agent-sandbox` accepts it. Before booting, `c -k` probes that host port and warns when no signer answers. The bridge is unauthenticated: any local host user can request signatures while it runs. Use it only on a single-user machine.

The dotfiles include [llm-ssh-agent-tcp.socket](../dotfiles/.config/systemd/user/llm-ssh-agent-tcp.socket), which listens on host loopback port 7777 and activates [llm-ssh-agent-tcp.service](../dotfiles/.config/systemd/user/llm-ssh-agent-tcp.service), a `systemd-socket-proxyd` bridge to `$XDG_RUNTIME_DIR/llm-agent.sock`. For a fresh installation, enable the listener:

```zsh
systemctl --user daemon-reload
systemctl --user enable --now llm-ssh-agent-tcp.socket
```

Before launching the workload, the guest entrypoint waits up to three seconds for the agent socket. If the bridge exits or the socket remains unavailable, it warns and launches the workload with `SSH_AUTH_SOCK` unset. When signing is disabled, the entrypoint skips the bridge and clears `SSH_AUTH_SOCK`.
