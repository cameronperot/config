# Path
# Precedence: ~/bin > ~/.local/bin > ~/.cargo/bin > ~/.juliaup/bin > inherited PATH > ~/gems/bin
typeset -U path
for d in "$HOME/.juliaup/bin" "$HOME/.cargo/bin" "$HOME/.local/bin" "$HOME/bin"; do
    if [ -d "$d" ]; then
        path=("$d" $path)
    fi
done
if [ -d "$HOME/gems/bin" ]; then
    path=($path "$HOME/gems/bin") # after inherited PATH
fi

# History
export HISTFILE="$HOME/.zsh_history"
export HISTSIZE=1000000
export SAVEHIST=$HISTSIZE

# Ruby
export BUNDLE_FORCE_RUBY_PLATFORM=true
export GEM_HOME="$HOME/gems"

# Editor
export VISUAL="nvim"
export EDITOR="nvim"
export SYSTEMD_EDITOR="nvim"
export JULIA_EDITOR="nvim"

# Language
export LANG=en_US.UTF-8

# Misc.
export VI_MODE_SET_CURSOR=true
export QT_QPA_PLATFORMTHEME="qt5ct:qt6ct" # Qt5 and Qt6 theming; needs qt5ct/qt6ct packages
export NO_AT_BRIDGE=1 # https://unix.stackexchange.com/questions/230238/x-applications-warn-couldnt-connect-to-accessibility-bus-on-stderr
export LIBVIRT_DEFAULT_URI="qemu:///system"
_zsh_bin="$(command -v zsh)" && export SHELL="$_zsh_bin"
unset _zsh_bin
export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
unset RANGER_LOAD_DEFAULT_RC
