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
| Forwarded SSH session | `~/.ssh/ssh_auth_sock` |
| SSH session without forwarding | Unset |
| Container | Socket supplied by the container launcher |

On a remote host, each Zsh login outside tmux updates `~/.ssh/ssh_auth_sock` to the forwarded socket. Tmux sessions keep that stable path, allowing existing panes to use a new forwarding socket after reconnecting.

The link is shared by all SSH sessions on the remote host. The newest forwarded login takes precedence, and its disconnection can leave the link stale. [`ssh_rc`](../dotfiles/.config/tmux/ssh_rc) can be installed as `~/.ssh/rc` to update the link before the shell starts.

## Container signing agent

`llm-ssh-agent.service` listens on `$XDG_RUNTIME_DIR/llm-agent.sock` and loads only `~/.ssh/llm_agent_ed25519`. The key must not have a passphrase because the service starts unattended.

`llm-ssh-agent-tcp.socket` exposes the signing agent on `127.0.0.1:7777` for `c -k`. Enable the agent, plus the TCP listener when using `c -k`:

```bash
systemctl --user enable --now llm-ssh-agent.service
systemctl --user enable --now llm-ssh-agent-tcp.socket
```

See the [dev-container signing setup](../dev-container/README.md#commit-signing) for key creation and verification.
