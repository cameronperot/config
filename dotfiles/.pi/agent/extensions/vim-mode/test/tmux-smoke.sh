#!/usr/bin/env bash
# Smoke test: drives the extension inside a real Pi in a detached tmux session.
#
# Each scenario clears the prompt, sends keys and polls the editor region (the lines between
# the editor's top border and its bottom border, which carries the mode label) until its pass
# condition holds or the timeout expires. No model call is made.

set -u

readonly TIMEOUT_SECONDS=15
readonly CLEAR_GAP_SECONDS=1.2

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
extension="$here/../index.ts"
session="vim-smoke-$$"
workdir=$(mktemp -d)
failures=0
last_clear=0

cleanup() {
	tmux kill-session -t "$session" 2>/dev/null
	rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

send() { tmux send-keys -t "$session" "$@"; }
type_text() { tmux send-keys -t "$session" -l -- "$1"; }
pane() { tmux capture-pane -t "$session" -p; }

# Prints the editor lines, between its top border and the bottom border with the mode label
editor_region() {
	pane | awk '
		{ line[NR] = $0 }
		/^── (INSERT|NORMAL)( |$)/ { bottom = NR }
		END {
			if (!bottom) exit 1
			for (top = bottom - 1; top > 0 && line[top] !~ /^─/; top--) {}
			for (i = top + 1; i < bottom; i++) print line[i]
		}'
}

# Prints everything below the bottom border, where Pi draws the autocomplete list
below_editor() {
	pane | awk '
		/^── (INSERT|NORMAL)( |$)/ { seen = 1; next }
		seen { print }'
}

mode() { pane | grep -oE '^── (INSERT|NORMAL)( |$)' | awk '{ print $2 }'; }

mode_is() { [[ $(mode) == "$1" ]]; }
region_is() { [[ $(editor_region) == "$1" ]]; }
region_contains() { editor_region | grep -qF -- "$1"; }
region_lacks() { ! editor_region | grep -qF -- "$1"; }
pane_has_line() { pane | grep -qE "^[[:space:]]*$1[[:space:]]*$"; }
pane_contains() { pane | grep -qF -- "$1"; }
below_contains() { below_editor | grep -qF -- "$1"; }
below_lacks() { ! below_editor | grep -qF -- "$1"; }

# Polls a command until it succeeds or the timeout expires
wait_until() {
	local deadline=$(($(date +%s) + TIMEOUT_SECONDS))
	until "$@"; do
		if (($(date +%s) >= deadline)); then return 1; fi
		sleep 0.1
	done
}

# Pi reads two Escapes in one terminal read as a single key, and an Escape followed closely by
# another key as an Alt chord, so each Escape goes in its own call and is followed by a pause
press_escape() {
	send Escape
	sleep 0.3
}

# Pi quits on a second ctrl+c within 500 ms, so clears are spaced apart
clear_prompt() {
	local now pause
	now=$(date +%s.%N)
	pause=$(awk -v now="$now" -v last="$last_clear" -v gap="$CLEAR_GAP_SECONDS" \
		'BEGIN { rest = gap - (now - last); print (rest > 0 ? rest : 0) }')
	sleep "$pause"
	send C-c
	last_clear=$(date +%s.%N)
	wait_until mode_is INSERT && wait_until region_is ""
}

# Waits for the editor region to hold exactly the given lines
region_equals() {
	local expected
	expected=$(printf '%s\n' "$@")
	[[ $(editor_region) == "$expected" ]]
}

scenario_startup() {
	mode_is INSERT
}

scenario_edit() {
	type_text abc
	press_escape
	wait_until mode_is NORMAL || return 1
	send h x i
	wait_until mode_is INSERT || return 1
	type_text Z
	press_escape
	wait_until mode_is NORMAL || return 1
	wait_until region_is "aZc"
}

scenario_paste() {
	local file="$workdir/paste.txt"
	local i
	: >"$file"
	for i in $(seq 1 15); do printf 'paste line %s\n' "$i" >>"$file"; done
	tmux load-buffer -b smoke "$file"
	tmux paste-buffer -p -b smoke -t "$session"
	wait_until region_contains "paste line 15" || return 1
	region_lacks "[paste #"
}

scenario_autocomplete() {
	type_text "/mod"
	wait_until below_contains "/model" || return 1
	press_escape
	wait_until mode_is NORMAL || return 1
	wait_until below_lacks "/model" || return 1
	region_is "/mod"
}

scenario_bash() {
	type_text '!echo vim-smoke-b'
	send Enter
	wait_until pane_has_line "vim-smoke-b" || return 1
	wait_until mode_is NORMAL || return 1
	wait_until region_is ""
}

scenario_history() {
	type_text '!echo vim-smoke-h'
	send Enter
	wait_until pane_has_line "vim-smoke-h" || return 1
	wait_until mode_is NORMAL || return 1
	press_escape
	send k
	wait_until region_is '!echo vim-smoke-h'
}

scenario_tree() {
	press_escape
	wait_until mode_is NORMAL || return 1
	send Escape
	sleep 0.1
	send Escape
	wait_until pane_contains "Session Tree" || return 1
	sleep 0.3
	send Escape
	wait_until pane_lacks_tree
}

pane_lacks_tree() { ! pane_contains "Session Tree"; }

scenario_external_editor() {
	type_text foo
	press_escape
	wait_until mode_is NORMAL || return 1
	send v v
	wait_until pane_contains "foo" || return 1
	wait_until nvim_is_open || return 1
	send ':s/foo/bar/' Enter
	wait_until pane_contains "bar" || return 1
	send ':wq' Enter
	wait_until mode_is NORMAL || return 1
	wait_until region_is "bar"
}

scenario_motions() {
	type_text "foo bar baz"
	press_escape
	wait_until mode_is NORMAL || return 1
	send 0 w x
	wait_until region_is "foo ar baz"
}

scenario_operators() {
	type_text "one two three"
	press_escape
	wait_until mode_is NORMAL || return 1
	send 0 d w .
	wait_until region_is "three"
}

scenario_undo() {
	type_text "one two"
	press_escape
	wait_until mode_is NORMAL || return 1
	send 0 d w
	wait_until region_is "two" || return 1
	send u
	wait_until region_is "one two"
}

# ctrl+- is the byte 0x1f, which tmux has no key name for
scenario_undo_key() {
	type_text "one two"
	press_escape
	wait_until mode_is NORMAL || return 1
	send 0 d w
	wait_until region_is "two" || return 1
	send -H 1f
	wait_until region_is "one two"
}

scenario_put() {
	type_text "abc"
	press_escape
	wait_until mode_is NORMAL || return 1
	send y y p
	wait_until region_equals "abc" "abc"
}

scenario_autoindent() {
	type_text "  x"
	press_escape
	wait_until mode_is NORMAL || return 1
	send o
	wait_until mode_is INSERT || return 1
	type_text y
	wait_until region_equals "  x" "  y"
}

# nvim fills the unused buffer rows with tildes, which Pi never draws
nvim_is_open() { pane | grep -qE '^~'; }

run_scenario() {
	local name=$1
	if clear_prompt && "scenario_${name//-/_}"; then
		echo "PASS $name"
	else
		echo "FAIL $name"
		pane
		failures=$((failures + 1))
	fi
}

main() {
	if ! tmux new-session -d -s "$session" -x 120 -y 30 -c "$workdir" \
		"pi --no-session -ne -e '$extension'"; then
		echo "FAIL tmux session"
		failures=$((failures + 1))
		return 1
	fi

	if wait_until scenario_startup; then
		echo "PASS startup"
	else
		echo "FAIL startup"
		pane
		failures=$((failures + 1))
		return 1
	fi

	local name
	for name in edit paste autocomplete bash history tree external-editor motions \
		operators undo undo-key put autoindent; do
		run_scenario "$name"
	done
}

main
((failures == 0))
