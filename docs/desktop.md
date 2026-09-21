# Desktop

The dotfiles provide separate [Sway](../dotfiles/.config/sway/config) and [i3](../dotfiles/.config/i3/config) configurations. Both use `Mod4` (the Super key), tabbed workspaces, vi-style navigation, and kitty as the terminal. This page describes the checked-in settings; installing dotfiles does not install the desktop applications or adapt hardware identifiers.

## Components

| Purpose | Sway | i3 |
| :--- | :--- | :--- |
| Status bar | [Waybar configuration](../dotfiles/.config/waybar/config.jsonc) and [style](../dotfiles/.config/waybar/style.css) | [i3status-rust](../dotfiles/.config/i3status-rust/config.toml), launched as `~/.cargo/bin/i3status-rs` |
| Application launcher | rofi (`run` and `window` modes) | `dmenu_run` |
| Wallpaper | `swaybg` | `feh` |
| Night lighting | [gammastep](../dotfiles/.config/gammastep/config.ini), launched with `gammastep-indicator` | [redshift](../dotfiles/.config/redshift.conf), launched with `redshift-gtk` |
| Locking | [swaylock](../dotfiles/.config/swaylock/config) and `swayidle` | `i3lock` and `xautolock` |
| Notifications | [mako settings](../dotfiles/.config/mako/config); startup is not explicitly declared in the main Sway file | Explicit Xfce notifyd startup |
| Screenshots | `grim`, `slurp`, `grimshot`, `jq`, and `wl-copy` | `xfce4-screenshooter` |

Both configurations launch `nm-applet` and use `pactl` for audio and `light` for brightness. Sway additionally launches `blueman-applet`. [Fuzzel settings](../dotfiles/.config/fuzzel/fuzzel.ini) are tracked, but the Sway launcher bindings select rofi. The shared font is JetBrainsMonoNL Nerd Font.

## Shared key bindings

`Mod` below means Super. Arrow keys also work wherever `h/j/k/l` is listed.

| Keys | Action |
| :--- | :--- |
| `Mod+Return` | Open kitty |
| `Mod+d` | Open the application launcher |
| `Mod+h/j/k/l` | Focus left/down/up/right |
| `Mod+Shift+h/j/k/l` | Move the focused window |
| `Mod+1` through `Mod+9` | Select workspace 1 through 9; add Shift to move a window there |
| `Mod+0` | Select workspace 10 |
| `Mod+Tab` | Return to the previous workspace |
| `Mod+;` / `Mod+v` | Set horizontal / vertical splitting |
| `Mod+s` / `Mod+w` / `Mod+e` | Stacking / tabbed / toggle split layout |
| `Mod+f` | Toggle fullscreen |
| `Mod+Shift+Space` / `Mod+Space` | Toggle floating / switch focus between tiling and floating |
| `Mod+r` | Enter resize mode; use direction keys, then Return or Escape to finish |
| `Mod+Shift+q` | Close the focused window |
| `Mod+z` | Show the scratchpad |
| `Mod+t` / `Mod+c` | Open Thunar / a Zenity calendar |
| `Ctrl+Alt+l` | Lock the screen |

The configs also bind workspaces beyond 10; those keys differ between Sway and i3. In Sway, `Mod+x` sends the focused container to the scratchpad; in i3 it targets floating windows. Sway reloads with `Mod+Shift+r`; i3 reloads with `Mod+Shift+c` and restarts with `Mod+Shift+r`. `Mod+Shift+e` opens the session exit prompt.

## Sway shortcuts and idle behavior

| Keys | Action |
| :--- | :--- |
| `Mod+g` | Open rofi's window selector |
| `Mod+n` | Open a timestamped Neovim scratch file under `/tmp/nvim` |
| `Mod+Ctrl+Shift+h/j/k/l` | Move the workspace to another output |
| `Mod+p` | Show the KeePassXC scratchpad window with the configured size and position |
| `Mod+m` | Dismiss notifications and clear the latest urgent window's urgency |
| `Mod+Print` | Save the focused output to `~/Pictures/screenshots/` |
| `Ctrl+Print` | Select a region and save it in that directory |
| `Ctrl+Shift+Print` | Select a region and copy it to the clipboard |

Create `~/Pictures/screenshots/` before using the save shortcuts; the commands do not create it. The background and swaylock configuration expect `~/Pictures/background.png`.

The configured idle timers lock after 900 seconds, power off outputs after 915 seconds, and request suspend after 930 seconds on battery or 3600 seconds otherwise. Output power is restored on activity. The configuration also locks before sleep; the power-key binding locks and requests suspend.

Waybar's caffeine button runs [caffeine.sh](../dotfiles/.config/waybar/caffeine.sh), which toggles a `systemd-inhibit --what=idle:sleep` process. It does not change the explicit swayidle timeout commands. Check the session's actual locking and suspend behavior before relying on the button to suppress them.

## Host-specific setup

| Location | Settings to review |
| :--- | :--- |
| Sway | Restart of the separately provisioned `kanshi.service`; Greybird-dark/Breeze-dark themes; `/usr/libexec/sway/layered-include` and distribution config directories |
| Waybar | Wi-Fi `wlp1s0`, sensor `k10temp` / `temp1_input`, backlight `intel_backlight`, and the Europe/Berlin clock |
| i3status-rust | Wi-Fi `wlp1s0`, battery `BAT1`, temperature chip selector, VPN interfaces, and Europe/Berlin / US/Eastern clocks |
| i3 | Named SYNA8017 touchpad and Elan TrackPoint; distribution-specific Xfce/polkit paths; brightness commands calling `~/bin/get_brightness.py`, which is not supplied here |
| Gammastep and Redshift | Manual latitude `50.95`, longitude `6.95`; day/night temperatures of 4800/3200 K and gamma `0.8` |

The [session environment file](../dotfiles/.config/environment.d/50-session.conf) sets `QT_QPA_PLATFORMTHEME=qt5ct:qt6ct` and `NO_AT_BRIDGE=1` for the systemd user environment. These settings are separate from shell startup files.

Right Alt is configured as Compose in both desktops; see [Compose](compose.md) for the mathematical character mappings. See [kitty](kitty.md) for terminal shortcuts and [dotfile syncing](dotfiles.md) for saving local configuration changes.
