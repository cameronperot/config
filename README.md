# Development Environment

Configuration and setup scripts for a Linux development environment built around Zsh, tmux, Neovim, and ranger, with additional dotfiles for sway/i3, kitty, and related desktop tooling. Also includes a [dev container](dev-container/README.md) for sandboxed LLM-assisted coding and instructions for a [KVM/QEMU dev VM](dev-vm/README.md).

## Layout

| Path | Purpose |
| :--- | :--- |
| `install.py` | Rsyncs `dotfiles/` into `$HOME`, installs Neovim, and adjusts the deployed copies to the host |
| `dotfiles/` | Tracked dotfiles |
| `dotfiles/bin/` | User scripts deployed to `~/bin` |
| `dotfiles/bin/agent-sandbox` | Python 3.12+ wrapper for `unshare`/bubblewrap isolation |
| `dotfiles.yaml` | Manifest for `sync_dotfiles.py`: what to sync, exclude and watch |
| `sync_dotfiles.py` | Copies dotfiles from `$HOME` back into `dotfiles/` |
| `environment.yml` | Micromamba environment `dev` (Python and core tooling) |
| `python/environments/` | Additional micromamba environments |
| `julia/julia-setup.jl` | Installs the default Julia package set |
| `dev-container/` | Dev container image, compose file, and entrypoint |
| `dev-vm/` | KVM + QEMU + libvirt VM instructions |
| `tests/` | Pytest coverage for installation, dotfile sync, container tools, and `agent-sandbox` |
| `pyproject.toml` | Pytest and coverage configuration (the repo is not a Python package) |
| `Makefile` | Shortcuts for the commands below (`make help`) |

## Install

Requires `rsync`, plus `wget` when Neovim is installed.

```bash
git clone https://github.com/cameronperot/environment-setup.git
cd environment-setup
./install.py   # or: make install
```

Options:

- `--neovim-version <version>`: Neovim release to install (default `stable`; `none` skips it)
- `--extract-appimage`: extract the appimage instead of running it directly (systems without FUSE)
- `--dry-run`: preview the dotfile changes without modifying anything

`make install` takes `NEOVIM_VERSION=vX.Y.Z` and `EXTRACT_APPIMAGE=1` for the same options.

## Documentation

| Page | Contents |
| :--- | :--- |
| [Zsh](docs/zsh.md) | Prompt, plugins, shell behavior, and key bindings |
| [tmux](docs/tmux.md) | Prefix, key bindings, plugins, and session behavior |
| [SSH](docs/ssh.md) | Personal and Git-signing agents, forwarding, and tmux |
| [Neovim](docs/nvim.md) | Installation, editor defaults, plugins, and key bindings |
| [Dotfiles](docs/dotfiles.md) | Sync commands, manifest rules, and safety checks |
| [Dev container](dev-container/README.md) | Container build, isolation, and Git signing |
| [Dev VM](dev-vm/README.md) | KVM, QEMU, and libvirt setup |

## Toolchains

| Command | Effect |
| :--- | :--- |
| `make mamba-install` | Install micromamba |
| `make mamba-init` | Initialize micromamba for the current shell |
| `make mamba-env` | Create the `dev` environment from `environment.yml` |
| `micromamba create -f python/environments/<name>.yml` | Create one of the additional environments |
| `make rust-install` | Install Rust via rustup |
| `make juliaup-install` | Install Julia via Juliaup |
| `julia julia/julia-setup.jl` | Install the default Julia packages |
| `make container-build` | Build the dev container image (see its [README](dev-container/README.md)) |
