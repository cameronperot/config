# ranger

The [ranger configuration](../dotfiles/.config/ranger/) combines a small settings override with a custom fuzzy selector, preview script, and file-opening rules. `install.py` copies these files to `~/.config/ranger`; ranger and its helper programs must be installed separately.

## Files and defaults

| File | Purpose |
| :--- | :--- |
| [rc.conf](../dotfiles/.config/ranger/rc.conf) | Show hidden files, relative line numbers, four lines of scroll offset, Git status, and the `Ctrl+F` binding |
| [commands.py](../dotfiles/.config/ranger/commands.py) | Define `fzf_select` |
| [scope.sh](../dotfiles/.config/ranger/scope.sh) | Preview text, documents, archives, and media |
| [rifle.conf](../dotfiles/.config/ranger/rifle.conf) | Choose applications to open files |

`rc.conf` intentionally contains overrides only; ranger's packaged defaults provide the remaining settings and bindings. From [Zsh](zsh.md), `Ctrl+R` opens ranger and restores the shell's existing command line when it exits.

## Fuzzy selection

Inside ranger, press `Ctrl+F` or run `:fzf_select` to search below the current directory. Selecting a directory enters it; selecting a file highlights it. Cancelling leaves the selection unchanged.

The command requires `fzf`. It chooses `fdfind`, then `fd`, then `find`, in that order. The fd variants include hidden entries, follow symlinks, and exclude `.git`; the `find -L` fallback follows symlinks but does not apply that exclusion. Search results therefore depend on the available finder.

## Previews

The preview script invokes external programs according to file type. Install the helpers needed for the files you browse; copying the script does not provide them.

| File type | Helpers referenced by the script |
| :--- | :--- |
| Source and text | `highlight`, `bat`, then `pygmentize`; plain-text fallback |
| JSON | `jq`, then `python -m json.tool` |
| PDF | `pdftotext`, `mutool`, and `exiftool` |
| Archives | `atool` / `bsdtar`, with separate `unrar` and `7z` handlers |
| HTML | `w3m`, `lynx`, `elinks`, and `pandoc` |
| Office documents | Format-specific tools such as `odt2txt`, `xlsx2csv`, `xls2csv`, or `pandoc` |
| Audio/video metadata | `mediainfo`, then `exiftool` |

The script calls the executable `bat` directly, so a shell alias for Debian's `batcat` does not satisfy that call. Lua files receive an explicit Lua highlighter selection to avoid MIME misidentification. Image rendering is conditional on ranger passing its image-preview flag; this repository's `rc.conf` does not enable image previews or choose a rendering backend. Video thumbnail and PDF image-preview handlers are commented out.

## Opening files

`rifle.conf` contains ordered rules based on extensions, MIME types, available programs, and whether a graphical session is present. Changing the installed applications can change which rule matches. Use `:open_with editor` or `:open_with pager` to select the corresponding labels; those rules use `VISUAL`/`EDITOR` and `PAGER` from the environment.

Adjust opener preferences in `rifle.conf` and preview behavior in `scope.sh`. Keep display settings and key bindings in `rc.conf`, and use the [dotfile sync workflow](dotfiles.md) to bring local changes back into this repository.
