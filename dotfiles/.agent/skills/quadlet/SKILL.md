---
name: quadlet
description: "Writes, reviews, migrates and troubleshoots Podman Quadlet units (.container, .network, .volume, .pod, .image, .build, .kube) for rootless or rootful systemd on Podman 5.4.2 and later, applying version gates, safe defaults and a review checklist, and hands the user the exact systemctl, generator and journalctl commands to run on the host. Use whenever Quadlet or podman-systemd.unit comes up: writing or fixing a .container, .pod, .network or .volume file, converting a podman run command or a Compose file to systemd, running a Podman container as a service or at boot, managing a Quadlet service's secrets, auto-update or rollback, or debugging a Quadlet unit that is not generated, will not start, keeps restarting or does not come up after reboot."
---

# quadlet

Produce Quadlet files that generate on the target host's Podman, start in the right order, survive restarts and reboots, and expose nothing by accident; systemd owns the lifecycle, the Quadlet source files are the only configuration.

Trailing input after `/skill:quadlet` describes the workload, the Quadlet or Compose files to work on, or the failure to diagnose; with no input, derive the task from the conversation and ask one consolidated question only when the rootless or rootful scope or the target directory is unclear.

## Hard rules

1. Never run host commands (`systemctl`, `podman`, the generator, `journalctl`, `loginctl`, `sysctl`); hand them to the user as one command block, unless the user explicitly tells you to run them.
2. Write into a live Quadlet search path (`~/.config/containers/systemd/`, `/etc/containers/systemd/`, …) only after explicit confirmation: after the next daemon-reload its `[Install]` section takes effect, so the next boot (or anything that starts it) runs it as a service.
3. Never edit a generated `.service` file and never tell the user to `systemctl enable` a Quadlet service: generated units are transient, and boot start comes from the `[Install]` section of the Quadlet file.
4. Use only keys that exist in Podman 5.4.2 unless the user or the repository's instructions state a newer host version; check every newer key against [references/versions.md](references/versions.md) and the versioned man page before using it.
5. Reference Quadlet-managed resources by file name (`Network=app.network`, `Volume=data.volume:/data`, `Image=api.build`, `Pod=stack.pod`) so Quadlet adds the dependency; on 5.4.2, `[Unit]` dependencies on other Quadlets use the generated service names (`After=db.service`, `Requires=app-network.service`).
6. No secret values in Quadlet files, drop-ins, or env files that are tracked or world-readable; use Podman secrets.
7. Use native keys; use `PodmanArgs=` only when no key exists, with a comment line above it naming the option and why.
8. Rootless: no `User=`, `Group=` or `DynamicUser=` in `[Service]` (`[Container] User=` is the UID inside the container), `WantedBy=default.target`, and boot start needs lingering.
9. Name every host-affecting effect in the report: a port published beyond loopback, a port below 1024, `:U` chown, `:Z`/`:z` relabel, a sysctl, lingering, auto-update, removal or recreation of a network or volume.
10. Report every host check the user has not run and returned as unverified; never describe an unrun check as passed.

## Workflow

1. **Scope.** Establish rootless or rootful (default rootless; rootful only for a stated need such as host-level networking, devices, or a system-wide service), the host Podman version (default 5.4.2), and the directory to write to (default the project directory the user names).
2. **Inventory.** List per workload: image and update policy, command, ports and who must reach them, state and its location, configuration files, secrets, dependencies between services, readiness signal, boot behaviour.
3. **Choose units.** One `.container` per service; one `.network` for any group of containers that talk to each other; `.volume` per piece of app-owned state; `.pod` only when containers must share localhost or IPC or start and stop as one; `.image` for a private-registry pull; `.build` for a locally built image.
4. **Write.** Apply the defaults below, then the request's explicit choices; read the routed references for anything beyond the defaults.
5. **Review.** Run the checklist below over every file; fix and repeat until a full pass is clean.
6. **Report.** Files written, deliberate exposures (rule 9), version-gated choices, then the host command block, with every result marked unverified until the user returns output.

For a **review** request, skip to step 5 and report each finding as `file:line`, severity (breaks generation or start / wrong behaviour / exposure / hygiene), and the fix.
For a **failure**, follow the troubleshooting tree in [references/operations.md](references/operations.md#troubleshooting) and ask for the specific command output it names.
For a **migration**, build the inventory from the source with [references/migration.md](references/migration.md), then continue at step 3.

## Defaults

| Setting | Default |
|---|---|
| Scope | Rootless, files under `~/.config/containers/systemd/` |
| Image | Fully qualified reference with a pinned tag or digest (`docker.io/library/postgres:17.2`); no `AutoUpdate=` |
| Auto-update | Opt-in only, and only with `HealthCmd=` + `Notify=healthy` so rollback can detect a bad image |
| Names | `ContainerName=`, `NetworkName=`, `VolumeName=` and `PodName=` set to the unit basename (`<base>-%i` in templates); pod members get distinct basenames (`stack.pod`, `stack-web.container`) |
| Ports | `PublishPort=127.0.0.1:<host>:<container>`; another address only when external exposure is requested |
| Restart | `[Service] Restart=on-failure` and `RestartSec=`; systemd owns restarts, never a Podman restart policy |
| Health | `HealthCmd=` when the image has a meaningful probe; add `Notify=healthy` and `HealthOnFailure=kill` when another unit depends on readiness or auto-update is on |
| Start timeout | `[Service] TimeoutStartSec=` covering the image pull plus time to healthy |
| Hardening | `NoNewPrivileges=true` always; `ReadOnly=true` and `DropCapability=ALL` with explicit add-backs only once the app's needs are known |
| State | Named `.volume` for app-owned state, bind mounts for user-managed config; nothing in the container layer, which Quadlet discards on every restart |
| Secrets | `podman secret create` + `Secret=<name>` mounted as a file; `type=env,target=VAR` only when the app reads its secret only from the environment |
| Logging | No `LogDriver=`; inherit the host's containers.conf default |
| Boot | `[Install] WantedBy=default.target` rootless, `WantedBy=multi-user.target` rootful, never both; `.network` and `.volume` need no `[Install]` because dependents pull them in |

## Review checklist

- **Generation:** extension is one of `.container`, `.volume`, `.network`, `.pod`, `.image`, `.build`, `.kube` (`.artifact` needs 5.7); required keys are present (`.container`: exactly one of `Image=` or `Rootfs=`; `.build`: `ImageTag=` plus `File=` or `SetWorkingDirectory=`; `.kube`: `Yaml=`); every key exists in its section for the host version; comments are whole lines starting with `#` or `;`, never trailing a value.
- **Scope:** the file's directory matches rootless or rootful, and so does every command in the handoff.
- **References:** every `.network`, `.volume`, `.image`, `.build` and `.pod` named in a key exists; a bare `Volume=name:` or `Network=name` appears only for a deliberately external resource.
- **Dependencies:** `[Unit]` dependencies on other Quadlets use generated service names on 5.4.2; no `After=`/`Wants=network-online.target` in rootless units, where Quadlet already adds `podman-user-wait-network-online.service`.
- **Boot:** `[Install]` is present when the service must start at boot, with the target for its scope, spelled correctly.
- **Names:** basename names set; unique across the user's Quadlets; no pod named like a container; no basename that shadows an existing service (`sshd.container` generates `sshd.service`).
- **Image:** fully qualified and pinned; `AutoUpdate=` only with health-gated readiness.
- **Ports:** bound to loopback unless exposure was requested; host ports below 1024 rootless are flagged.
- **Storage:** state lives in volumes; bind-mount sources exist on the host; relative paths start with `./`; every `:U`, `:Z` or `:z` is justified.
- **Secrets:** no secret value in any file; each `Secret=` has a matching `podman secret create` in the handoff.
- **Readiness:** the `HealthCmd=` binary exists in the image; `Notify=healthy` has a `HealthCmd=`; `TimeoutStartSec=` covers pull plus start period.
- **Restart:** `Restart=` sits in `[Service]`; no `--restart` in `PodmanArgs=`.
- **Escape hatches:** each `PodmanArgs=` or `GlobalArgs=` has a comment and no native-key equivalent for the host version.

## Host command block

End every authoring or fix report with one block like this, adapted to the units and scope, with specifiers expanded to shell form (`%h` → `~`); rootful drops `--user`, uses `/etc/containers/systemd/` and `sudo`, and checks `/run/systemd/generator/multi-user.target.wants/`.

```bash
# Host facts (return this output first)
podman --version
podman info --format 'cgroup={{.Host.CgroupsVersion}} logdriver={{.Host.LogDriver}}'
# Install (skip if the files were written in place)
mkdir -p ~/.config/containers/systemd
cp app.network db.container web.container ~/.config/containers/systemd/
# Secrets (once; reads the value without echoing it)
read -rs DB_PASSWORD && printf '%s' "$DB_PASSWORD" | podman secret create db-password - && unset DB_PASSWORD
# Check generation, then load
/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun
systemctl --user daemon-reload
systemd-analyze --user --generators=true verify web.service
# Start and inspect
systemctl --user start web.service
systemctl --user status web.service db.service
journalctl --user -u web.service -e
podman logs web
# Boot persistence (lingering needs root once per user)
loginctl show-user "$USER" --property=Linger
ls "$XDG_RUNTIME_DIR/systemd/generator/default.target.wants/"
```

When lingering is off, add `sudo loginctl enable-linger <user>` and name it under rule 9.

## References

| File | Read when |
|---|---|
| [references/lifecycle.md](references/lifecycle.md) | Always for authoring: search paths, generated names, `[Install]`, lingering, dependencies, templates, drop-ins, specifiers, editing and removing units |
| [references/container.md](references/container.md) | Writing or reviewing a `.container`: image, ports, networking, volumes and UID mapping, SELinux, secrets, health, restart, hardening, resources, logging |
| [references/resources.md](references/resources.md) | Any `.network`, `.volume`, `.pod`, `.image`, `.build`, `.kube` or `.artifact` file |
| [references/operations.md](references/operations.md) | Secrets lifecycle, private registries, auto-update and rollback, the `podman quadlet` CLI, and troubleshooting |
| [references/versions.md](references/versions.md) | The host runs Podman newer than 5.4.2, a key is not in the 5.4.2 lists, or you need the versioned documentation |
| [references/migration.md](references/migration.md) | Converting a `podman run` command, a Compose file or `podman generate systemd` output |

When a key's exact semantics matter, read the man page for the host version at `https://docs.podman.io/en/v<version>/markdown/podman-systemd.unit.5.html` (5.4.2 by default; from 6.0 the per-type pages such as `podman-container.unit.5.html`), never `/en/latest/`, which documents unreleased Podman.
