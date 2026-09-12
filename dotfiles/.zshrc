# Antidote, pinned to the v2.3.0 commit for reproducibility; bump the tag and pin deliberately
export ANTIDOTE_HOME="${HOME}/.antidote/cache"
_antidote_pin="9bb69ab99c6f05d6e6ae237f7ce222eeeb5b4a14"
if [ ! -s "${HOME}/.antidote/antidote.zsh" ]; then
    git clone --depth 1 --branch v2.3.0 https://github.com/mattmc3/antidote "${HOME}/.antidote" || {
        rm -rf "${HOME}/.antidote"
        echo "zshrc: could not clone antidote v2.3.0" >&2
        return 1
    }
fi
# Refuse to run an antidote that drifted from the pin (antidote update self-pulls)
if [ "$(git -C "${HOME}/.antidote" rev-parse HEAD)" != "$_antidote_pin" ]; then
    echo "zshrc: ${HOME}/.antidote is not at the pinned commit; rm -rf it or bump the pin" >&2
    return 1
fi
source "${HOME}/.antidote/antidote.zsh"

# oh-my-zsh settings
# Disable omz's update checker
zstyle :omz:update mode disabled

# Plugins (static bundle; regenerated when it is stale)
_antidote_bundle_txt="${HOME}/.zsh_plugins.txt"
_antidote_bundle_zsh="${HOME}/.zsh_plugins.zsh"
if [[ ! "$_antidote_bundle_zsh" -nt "$_antidote_bundle_txt" || ! "$_antidote_bundle_zsh" -nt "${HOME}/.antidote/antidote.zsh" ]]; then
    _antidote_tmp="$(mktemp "${_antidote_bundle_zsh}.XXXXXX")"
    if antidote bundle < "${_antidote_bundle_txt}" >| "${_antidote_tmp}" && [[ -s "${_antidote_tmp}" ]]; then
        mv "${_antidote_tmp}" "${_antidote_bundle_zsh}"
    else
        rm -f "${_antidote_tmp}"
        echo "zshrc: could not regenerate ${_antidote_bundle_zsh} from ${_antidote_bundle_txt}" >&2
    fi
fi
[[ -s "${_antidote_bundle_zsh}" ]] && source "${_antidote_bundle_zsh}"
unset _antidote_bundle_txt _antidote_bundle_zsh _antidote_tmp _antidote_pin

# history-substring-search
bindkey -M vicmd "k" history-substring-search-up
bindkey -M vicmd "j" history-substring-search-down

# Prompt theme
ZSH_THEME_GIT_PROMPT_PREFIX="("
ZSH_THEME_GIT_PROMPT_SUFFIX=")"
ZSH_THEME_GIT_PROMPT_DIRTY="*"
ZSH_THEME_GIT_PROMPT_CLEAN=""
PROMPT='%B%{$fg[green]%}%n@%m %{$fg[blue]%}%2~%b%{$fg[cyan]%}$(git_prompt_info)%{$reset_color%} ⟩ '
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
unsetopt SHARE_HISTORY
HISTORY_IGNORE="(*password*|*secret*|*PASSWORD*|*SECRET*)"

# Aliases

# Key bindings (insert mode; main keymap is viins via vi-mode)
bindkey -s "^r" " ranger^M" # ctrl-r -> ranger
bindkey -s "^n" " nvim^M"   # ctrl-n -> nvim
bindkey -s "^h" " hstr^M"   # ctrl-h -> hstr
alias hh=hstr               # hh -> hstr
KEYTIMEOUT=1                # for esc in zsh vim mode

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
