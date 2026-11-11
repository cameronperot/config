# Container units

Contents: [Keys in 5.4.2](#keys-in-542) · [Image and command](#image-and-command) · [Ports](#ports) · [Networking](#networking) · [Storage](#storage) · [UID mapping](#uid-mapping) · [SELinux](#selinux) · [Environment and secrets](#environment-and-secrets) · [Health and readiness](#health-and-readiness) · [Restart and stop](#restart-and-stop) · [Hardening](#hardening) · [Resources](#resources) · [Logging](#logging)

## Keys in 5.4.2

Exactly one of `Image=` or `Rootfs=` is required.
The complete `[Container]` key set in Podman 5.4.2; anything else needs a newer host ([versions.md](versions.md)) or `PodmanArgs=`:

AddCapability, AddDevice, AddHost, Annotation, AutoUpdate, CgroupsMode, ContainerName, ContainersConfModule, DNS, DNSOption, DNSSearch, DropCapability, Entrypoint, Environment, EnvironmentFile, EnvironmentHost, Exec, ExposeHostPort, GIDMap, GlobalArgs, Group, GroupAdd, HealthCmd, HealthInterval, HealthLogDestination, HealthMaxLogCount, HealthMaxLogSize, HealthOnFailure, HealthRetries, HealthStartPeriod, HealthStartupCmd, HealthStartupInterval, HealthStartupRetries, HealthStartupSuccess, HealthStartupTimeout, HealthTimeout, HostName, Image, IP, IP6, Label, LogDriver, LogOpt, Mask, Mount, Network, NetworkAlias, NoNewPrivileges, Notify, PidsLimit, Pod, PodmanArgs, PublishPort, Pull, ReadOnly, ReadOnlyTmpfs, Rootfs, RunInit, SeccompProfile, Secret, SecurityLabelDisable, SecurityLabelFileType, SecurityLabelLevel, SecurityLabelNested, SecurityLabelType, ShmSize, StartWithPod, StopSignal, StopTimeout, SubGIDMap, SubUIDMap, Sysctl, Timezone, Tmpfs, UIDMap, Ulimit, Unmask, User, UserNS, Volume, WorkingDir.

Not in 5.4.2, often reached for: `Memory=`, `ReloadCmd=`, `ReloadSignal=`, `Retry=`, `HttpProxy=`, `AppArmor=`, `ImageVolume=`, `ServiceName=` (only `[Pod]` has it).

## Image and command

- `Image=` takes a fully qualified reference (`registry/namespace/name:tag` or `@sha256:…`); short names depend on the host's registries.conf and fail or resolve unpredictably under systemd.
- Pin a tag or digest; a moving tag such as `latest` changes the deployed version at whatever moment the image is next pulled, with no rollback.
- `Pull=` controls pulling at start (`missing` is Podman's default; `newer` and `always` add a registry round trip to every start); auto-update replaces repeated pulls as the update mechanism.
- `Image=x.image` pulls through a `.image` unit (private registries with `AuthFile=`, see [resources.md](resources.md#image)); `Image=x.build` uses a `.build` unit's image.
- `Exec=` appends arguments after the image, so the image's `ENTRYPOINT` still runs; `Entrypoint=` replaces it.
- `RunInit=true` runs an init as PID 1 to reap zombies, for images whose entrypoint spawns children without reaping them.

## Ports

- `PublishPort=` formats: `ip:hostPort:containerPort`, `ip::containerPort`, `hostPort:containerPort`, `containerPort`, each optionally with `/tcp` or `/udp`.
- Without an IP, the port binds on every host interface, so the default here is `127.0.0.1:hostPort:containerPort`; a reverse proxy on the host then reaches it on loopback.
- Rootless containers cannot bind host ports below `net.ipv4.ip_unprivileged_port_start` (1024 by default); `AddCapability=NET_BIND_SERVICE` does not help because the port is bound outside the container.
- The options for a low port are a host-wide sysctl (`net.ipv4.ip_unprivileged_port_start`, set in `/etc/sysctl.d/`), publishing a high port behind a firewall redirect or reverse proxy, or a rootful unit; each is a host decision for the user (rule 9).
- Containers on the same `.network` reach each other on container ports directly; publish only what the host or outside clients need.

## Networking

- Rootless containers without `Network=` get pasta networking: outbound access works, but containers cannot resolve or reach each other by name.
- Put containers that talk to each other on a shared `.network` (`Network=app.network`); its bridge has DNS enabled by default, and each container is reachable by its `ContainerName=` and any `NetworkAlias=`.
- `Network=host` shares the host's network namespace and makes `PublishPort=` meaningless; `Network=none` gives loopback only, for jobs that need no network.
- `Network=x.container` joins another container's network namespace, as pod members do, without a pod.
- A container may list several `Network=` lines to join several networks.

## Storage

- `Volume=data.volume:/var/lib/app` mounts a Quadlet-managed named volume and adds its dependency; `Volume=name:/path` without the suffix mounts an unmanaged named volume, which Podman creates on first use with no unit.
- `Volume=/abs/host/path:/path[:options]` or `Volume=%h/app/config:/etc/app:ro` bind-mounts a host path, which must already exist; `Volume=./conf:/etc/app:ro` resolves against the Quadlet file's directory.
- Volume options: `ro`, `z`/`Z` (SELinux, below), `U` (chown, below), `idmap`, `noexec`/`nosuid`/`nodev`.
- `Mount=` takes the `--mount` syntax for types `bind`, `volume`, `tmpfs`, `image`, `devpts`, and also resolves `.volume`/`.image` sources.
- `Tmpfs=/run/app:rw,size=64m` adds a tmpfs; with `ReadOnly=true`, `ReadOnlyTmpfs=` (default `true`) already mounts tmpfs on `/dev`, `/dev/shm`, `/run`, `/tmp` and `/var/tmp`.
- For an image-backed container, nothing written outside a volume or bind mount survives a restart.

## UID mapping

- Rootless Podman maps the host user to root (UID 0) in the container and the user's subordinate IDs (`/etc/subuid`, `/etc/subgid`) to every other container UID.
- A container process running as a non-root UID therefore owns files on the host as a subordinate UID, and cannot write a bind-mounted directory owned by the host user.
- Fixes, in order of preference:
    1. Keep the app's state in a named volume, which lives in the user's container storage instead of a host directory with fixed ownership.
    2. `UserNS=keep-id:uid=<app uid>,gid=<app gid>` maps the host user to the app's UID inside the container, so bind-mounted files stay owned by the host user.
    3. The `:U` volume option recursively chowns the host path to the container UID on every start; it modifies host files and is slow on large trees (rule 9).
- `UserNS=keep-id` without options maps the host UID to the same UID inside the container and may change the user the image expects to run as; `keep-id:size=<n>` limits how many subordinate IDs it uses.
- `[Container] User=` and `Group=` set the numeric UID and GID inside the container; `Group=` requires `User=`.
- A container in a pod uses the pod's user namespace; set `UserNS=` on the `.pod`.

## SELinux

- On SELinux hosts (Fedora, RHEL and derivatives), a bind mount needs a label before the container can access it: `:Z` for content private to one container, `:z` for content shared by several.
- Never relabel a home directory, `/`, `/usr`, `/etc` or another system path; use `SecurityLabelDisable=true` for the container instead, and name it.
- On hosts without SELinux (Debian, Ubuntu use AppArmor), `:z`/`:Z` are no-ops, so they are harmless in files meant for both.

## Environment and secrets

- `Environment=KEY=value` per variable or several per line with systemd quoting; values are literal.
- `EnvironmentFile=` reads `KEY=value` lines (absolute, `%h/…` or relative to the unit file); keep such files mode 0600 and untracked when they hold anything sensitive.
- Avoid `EnvironmentHost=true`, which copies the whole host environment of the service manager into the container.
- `Secret=db-password` mounts the Podman secret at `/run/secrets/db-password` (mode 0444 by default); `target=` changes the path, `uid=`, `gid=`, `mode=` the file ownership and mode.
- `Secret=db-password,type=env,target=DB_PASSWORD` exposes it as an environment variable instead, for apps that read nothing else; an environment variable is inherited by every child process and shows up in anything that dumps the environment.
- Prefer apps' `*_FILE` conventions (`POSTGRES_PASSWORD_FILE=/run/secrets/db-password`) over `type=env`.
- Secrets are per user (rootless) or per host (rootful) and must exist before the unit starts; creation and rotation are in [operations.md](operations.md#secrets).

## Health and readiness

- By default Quadlet reports the service ready when conmon has started the container (`--sdnotify=conmon`), which says nothing about the app.
- `HealthCmd=` runs inside the container, so its binary (and a shell, for shell syntax) must exist in the image; `HealthCmd=none` disables an image-defined check.
- Tune with `HealthInterval=`, `HealthTimeout=`, `HealthRetries=`, `HealthStartPeriod=`; slow-starting apps can use the `HealthStartup*` keys for a separate startup probe.
- `Notify=healthy` delays the ready notification until the first passing health check, so `After=` on this service waits for a healthy app and auto-update can detect a broken image.
- `Notify=true` passes systemd's notify socket to an app that calls `sd_notify` itself; use it only when the app does.
- `HealthOnFailure=kill` kills the container when it turns unhealthy; with `[Service] Restart=on-failure` systemd then restarts it; other actions are `none`, `restart` and `stop`, but `kill` hands the decision to systemd.
- `TimeoutStartSec=` must exceed the pull time plus the time to the first passing check, or systemd fails the start.

## Restart and stop

- Put `Restart=on-failure` and `RestartSec=` (for example `10`) in `[Service]`; never add `--restart` through `PodmanArgs=`.
- systemd stops restarting after `StartLimitBurst=` failures within `StartLimitIntervalSec=` (both in `[Unit]`; systemd's defaults are 5 in 10 s); after fixing the cause, `systemctl --user reset-failed <unit>` clears the state.
- `StopSignal=` and `StopTimeout=` control the graceful stop; keep `StopTimeout=` below `[Service] TimeoutStopSec=`.

## Hardening

- `NoNewPrivileges=true` always; Podman's default is `false`.
- `DropCapability=ALL` with explicit `AddCapability=` lines, once the app's needs are known; images that switch users at start need `SETUID`/`SETGID`, ones that chown at start need `CHOWN`/`FOWNER`.
- `ReadOnly=true` with `Volume=` or `Tmpfs=` for each writable path, once the app's write paths are known.
- `SeccompProfile=`, `Mask=`, `Unmask=` and `SecurityLabel*` exist for finer control; never use `PodmanArgs=--privileged` without the user's explicit request.
- `AddDevice=` passes a device; a leading `-` (`AddDevice=-/dev/dri`) adds it only when present on the host.

## Resources

- 5.4.2 has `PidsLimit=`, `Ulimit=`, `ShmSize=` and `Sysctl=` but no memory or CPU keys; `[Service]` passes through to systemd, so use its resource controls (`MemoryMax=512M`, `CPUQuota=150%`), which bound the service's cgroup including the container (`Memory=` arrives in Podman 5.5).
- `CgroupsMode=` defaults to `split` under Quadlet, unlike the CLI default `enabled`; containers in a pod need `no-conmon` or `enabled` for pod-level limits to apply.

## Logging

- Leave `LogDriver=` unset so the container inherits the host's containers.conf default, which is journald when the journal is usable and `k8s-file` otherwise; check the effective driver with `podman info --format '{{.Host.LogDriver}}'` before telling the user where the container's output is.
- With journald, the output appears in `journalctl --user -u <unit>`; `podman logs <name>` works with both drivers.
- Journal retention is configured in journald, not per container.
