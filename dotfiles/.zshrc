# Antidote, pinned to the v2.3.0 commit for reproducibility; bump the tag and pin deliberately
export ANTIDOTE_HOME="${HOME}/.antidote/cache"
# oh-my-zsh settings
# Disable omz's update checker
zstyle :omz:update mode disabled

# Keep the basic shell usable if plugin installation fails
() {
    local pin="9bb69ab99c6f05d6e6ae237f7ce222eeeb5b4a14" bootstrap
    local bundle_txt="${HOME}/.zsh_plugins.txt" bundle_zsh="${HOME}/.zsh_plugins.zsh" bundle_tmp
    if [[ ! -e "${HOME}/.antidote" && ! -L "${HOME}/.antidote" ]]; then
        bootstrap="$(mktemp -d "${HOME}/.antidote-bootstrap.XXXXXX")" || return 1
        {
            git clone --depth 1 --branch v2.3.0 https://github.com/mattmc3/antidote "${bootstrap}/repo" || return 1
            [[ "$(git -C "${bootstrap}/repo" rev-parse HEAD)" == "$pin" ]] || {
                print -u2 -- "zshrc: downloaded antidote does not match the pinned commit"
                return 1
            }
            # A concurrent shell may have installed the same release already
            mv -T -n -- "${bootstrap}/repo" "${HOME}/.antidote" || return 1
        } always {
            rm -rf -- "$bootstrap"
        }
    fi
    # Refuse to run an antidote that drifted from the pin (antidote update self-pulls)
    if [[ ! -s "${HOME}/.antidote/antidote.zsh" || "$(git -C "${HOME}/.antidote" rev-parse HEAD)" != "$pin" ]]; then
        print -u2 -- "zshrc: ${HOME}/.antidote is incomplete or differs from the pinned commit; inspect and repair it"
        return 1
    fi
    source "${HOME}/.antidote/antidote.zsh" || return 1

    # Plugins (static bundle; regenerated when it is stale)
    if [[ ! "$bundle_zsh" -nt "$bundle_txt" || ! "$bundle_zsh" -nt "${HOME}/.antidote/antidote.zsh" ]]; then
        bundle_tmp="$(mktemp "${bundle_zsh}.XXXXXX")" || return 1
        if antidote bundle < "$bundle_txt" >| "$bundle_tmp" && [[ -s "$bundle_tmp" ]]; then
            mv -- "$bundle_tmp" "$bundle_zsh" || return 1
        else
            rm -f -- "$bundle_tmp"
            print -u2 -- "zshrc: could not regenerate ${bundle_zsh} from ${bundle_txt}"
            return 1
        fi
    fi
    source "$bundle_zsh"
} || print -u2 -- "zshrc: plugins unavailable; continuing with the basic shell configuration"

# history-substring-search
if (( $+widgets[history-substring-search-up] )); then
    bindkey -M vicmd "k" history-substring-search-up
    bindkey -M vicmd "j" history-substring-search-down
fi

# Prompt theme
ZSH_THEME_GIT_PROMPT_PREFIX="("
ZSH_THEME_GIT_PROMPT_SUFFIX=")"
ZSH_THEME_GIT_PROMPT_DIRTY="*"
ZSH_THEME_GIT_PROMPT_CLEAN=""
PROMPT='%B%{$fg[green]%}%n@%m %{$fg[blue]%}%2~%b%{$fg[cyan]%}$(git_prompt_info)%{$reset_color%} ⟩ '
if (( ! $+functions[git_prompt_info] )); then
    PROMPT='%B%F{green}%n@%m %F{blue}%2~%b%f ⟩ '
fi
MODE_INDICATOR="%F{yellow}+%f"
RPROMPT=''

# http://zsh.sourceforge.net/Doc/Release/Options.html#Description-of-Options
setopt EXTENDED_GLOB
setopt EXTENDED_HISTORY
setopt HIST_IGNORE_SPACE
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_NO_STORE
setopt HIST_REDUCE_BLANKS
setopt HIST_VERIFY
setopt HIST_SAVE_NO_DUPS
unsetopt SHARE_HISTORY INC_APPEND_HISTORY
setopt INC_APPEND_HISTORY_TIME
HISTORY_IGNORE="(#i)(*password*|*secret*)"

# Reject matching commands from interactive history as well as the history file
_zsh_filter_history() {
    [[ "$1" != ${~HISTORY_IGNORE} ]]
}
autoload -Uz add-zsh-hook
add-zsh-hook zshaddhistory _zsh_filter_history

# Key bindings (insert mode; main keymap is viins via vi-mode)
_zsh_open_ranger() {
    zle -I
    command ranger </dev/tty
    local result=$?
    zle reset-prompt
    return $result
}
_zsh_open_nvim() {
    zle -I
    command nvim </dev/tty
    local result=$?
    zle reset-prompt
    return $result
}
zle -N _zsh_open_ranger
zle -N _zsh_open_nvim
bindkey -M viins "^r" _zsh_open_ranger
if (( $+widgets[fzf-history-widget] )); then
    bindkey -M viins "^h" fzf-history-widget
else
    bindkey -M viins "^h" history-incremental-search-backward
fi
bindkey -M viins "^n" _zsh_open_nvim
KEYTIMEOUT=1 # for esc in zsh vim mode

# Fuzzy completion groups, colors, and directory previews
zstyle ':completion:*:descriptions' format '[%d]'
zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}
zstyle ':completion:*:*:*:*:*' menu no
zstyle ':fzf-tab:*' switch-group '<' '>'
export FZF_DEFAULT_OPTS="${FZF_DEFAULT_OPTS:---height=50% --layout=reverse --border}"
if (( $+commands[lsd] )); then
    zstyle ':fzf-tab:complete:cd:*' fzf-preview 'lsd --color=always -- "$realpath"'
    export FZF_ALT_C_OPTS="--preview 'lsd --color=always -- {}'"
fi
if (( $+commands[bat] )); then
    export FZF_CTRL_T_OPTS="--preview 'if [ -f {} ]; then bat --color=always --style=numbers --line-range=:200 -- {}; fi'"
elif (( $+commands[batcat] )); then
    alias bat=batcat
    export FZF_CTRL_T_OPTS="--preview 'if [ -f {} ]; then batcat --color=always --style=numbers --line-range=:200 -- {}; fi'"
fi

# Exports
[[ -t 0 ]] && export GPG_TTY="$(tty)"

# Source files
for file in .config/zsh/ssh-agent.zsh .bash_aliases .local_aliases .local_exports
do
    if [ -f "${HOME}/${file}" ]; then
        source "${HOME}/${file}"
    fi
done

# Kitty complete (cached; regenerated when the kitty binary changes)
if [ -x "$(command -v kitty)" ]; then
    _kitty_cache="${XDG_CACHE_HOME:-$HOME/.cache}/kitty-zsh-completions.zsh"
    if [[ ! -s "$_kitty_cache" || "$(command -v kitty)" -nt "$_kitty_cache" ]]; then
        _kitty_tmp="$(mktemp "${_kitty_cache}.XXXXXX")"
        if kitty + complete setup zsh >| "$_kitty_tmp" && [[ -s "$_kitty_tmp" ]]; then
            mv "$_kitty_tmp" "$_kitty_cache"
        else
            rm -f "$_kitty_tmp"
        fi
    fi
    [[ -s "$_kitty_cache" ]] && source "$_kitty_cache"
    unset _kitty_cache _kitty_tmp
fi

# Micromamba
if [[ -f "${HOME}/.mamba_init.sh" ]]; then
    source "${HOME}/.mamba_init.sh"
fi

# zoxide
if [ -x "$(command -v zoxide)" ]; then
    eval "$(zoxide init zsh --cmd z)" # defines z and zi (zi needs fzf)
fi
