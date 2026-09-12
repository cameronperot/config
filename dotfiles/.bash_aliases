# General
alias clearnvimswap="find ~/.local/state/nvim/swap -name '*.swp' -delete 2>/dev/null"
alias mm="micromamba"
alias n="nvim"
alias nn="nvim --clean"
alias sn="sudoedit"
alias sshk="kitten ssh"
alias ta="tmux a"
alias updatenvim="wget -O /tmp/nvim.appimage https://github.com/neovim/neovim/releases/download/stable/nvim.appimage && mv /tmp/nvim.appimage ~/bin/nvim && chmod u+x ~/bin/nvim"

# LSD
alias l="lsd -lFh"      # long, classify, human-readable
alias la="lsd -lAFh"    # long, almost-all, classify, human-readable
alias lr="lsd -tRFh"    # tree, recursive, classify, human-readable
alias lt="lsd --tree"   # tree
alias ll="lsd -l"       # long
alias ldot="lsd -ld .*" # long, directory, dotfiles
alias lS="lsd -1FSh"    # one-per-line, classify, size-sort, human-readable
alias lart="lsd -1Fart" # one-per-line, classify, almost-all, reverse, timesort
alias lrt="lsd -1Frt"   # one-per-line, classify, reverse, timesort
alias lsr="lsd -lARFh"  # long, almost-all, recursive, classify, human-readable
alias lsn="lsd -1"      # one-per-line

# uv
alias uvr="uv run"
alias uvp="uv run python"
alias uvl="uv lock"
alias uvs="uv sync"
alias uva="source ./.venv/bin/activate"
alias uvd="deactivate"
alias uvup="curl -LsSf https://astral.sh/uv/install.sh | sh"
alias ruffup="curl -LsSf https://astral.sh/ruff/install.sh | sh"
alias tyup="curl -LsSf https://astral.sh/ty/install.sh | sh"

# Podman
alias pm="podman"
alias pma="podman attach"
alias pmc="podman container"
alias pme="podman exec"
alias pmi="podman image"
alias pmp="podman pull"
alias pmr="podman run"
alias pmv="podman volume"
alias pmcom="podman-compose"

# systemctl user
alias svc="systemctl --user"
alias svc-disable="systemctl --user disable"
alias svc-enable="systemctl --user enable"
alias svc-list="systemctl --user list-units --type=service --state=running | grep -v -i 'healthcheck'"
alias svc-logs="journalctl --user -u"
alias svc-reload="systemctl --user daemon-reload"
alias svc-restart-all="find ~/.config/containers/systemd/ -name '*.container' -exec basename {} .container \; | xargs -r systemctl --user restart"
alias svc-restart="systemctl --user restart"
alias svc-start="systemctl --user start"
alias svc-status="systemctl --user status"
alias svc-stop-all="find ~/.config/containers/systemd/ -name '*.container' -exec basename {} .container \; | xargs -r systemctl --user stop"
alias svc-stop="systemctl --user stop"
