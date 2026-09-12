# SSH

The dotfiles include separate SSH agents for personal keys and container Git signing. The [systemd user units](../dotfiles/.config/systemd/user/) are installed but not enabled.

## Personal agent

Enable the personal agent after installing the dotfiles:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ssh-agent.service
```

It listens on `$XDG_RUNTIME_DIR/ssh-agent.sock` and starts empty. Add `AddKeysToAgent yes` to `~/.ssh/config` to add keys after first use and retain them until the service stops.

Zsh selects the socket for each session:

| Session | `SSH_AUTH_SOCK` |
| :--- | :--- |
| Local shell | `$XDG_RUNTIME_DIR/ssh-agent.sock` |
| SSH shell outside tmux | Original forwarded socket, or unset without forwarding |
| Remote tmux shell | `$XDG_RUNTIME_DIR/ssh-forwarded-agent.sock`, even before forwarding is available |
| Container | Socket supplied by the container launcher |

The installer copies [`ssh_rc`](../dotfiles/.config/tmux/ssh_rc) to `~/.ssh/rc`, replacing its contents, and creates `~/.ssh` with mode `700` when absent. Merge any custom SSH rc logic before installing. SSH must permit user rc execution (`PermitUserRC yes`); the hook runs before the shell or command, including direct attachment with `ssh -A -t host 'tmux attach'`. It also installs X11 authentication cookies because a user rc replaces sshd's automatic X11 setup.

Each forwarded SSH login atomically updates `$XDG_RUNTIME_DIR/ssh-forwarded-agent.sock`. Only the SSH hook updates the link; starting or sourcing Zsh never changes its target. Existing remote tmux panes keep this stable path and use the newest connection on their next agent request. Ordinary SSH shells retain their own connection's socket. Tmux keeps its default environment updates for new panes.

SSH sessions must supply an existing `$XDG_RUNTIME_DIR`, normally `/run/user/<UID>` on systems using `pam_systemd`. The hook reports an error if the directory is unavailable or the forwarded path is not a socket. Remote tmux shells warn and retain their inherited socket when the runtime directory is unavailable. The link is recreated on the next forwarded login if the runtime directory was removed after logout or reboot. The personal `ssh-agent.sock` and container signing sockets remain separate.

The newest forwarded login serves all remote tmux panes for the account. A login without forwarding leaves the link unchanged. Disconnecting the selected connection leaves the link stale until another forwarded login; there is no automatic fallback to older connections. Processes running as the remote user can access the selected agent, so only forward to trusted hosts and workloads.

After running the installer, reconnect with forwarding and source `~/.config/zsh/ssh-agent.zsh` once in each existing remote Zsh pane to select the new path. Restart applications that inherited the old socket path. Reload `~/.tmux.conf` for running tmux servers.

## Container signing agent

`llm-ssh-agent.service` listens on `$XDG_RUNTIME_DIR/llm-agent.sock` and loads only `~/.ssh/llm_agent_ed25519`. The key must not have a passphrase because the service starts unattended.

`llm-ssh-agent-tcp.socket` exposes the signing agent on `127.0.0.1:7777` for `c -k`. Enable the agent, plus the TCP listener when using `c -k`:

```bash
systemctl --user enable --now llm-ssh-agent.service
systemctl --user enable --now llm-ssh-agent-tcp.socket
```

See the [dev-container signing setup](../dev-container/README.md#commit-signing) for key creation and verification.
