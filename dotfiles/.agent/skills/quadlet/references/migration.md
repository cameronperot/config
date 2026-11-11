# Migration

Contents: [Procedure](#procedure) · [Compose to Quadlet](#compose-to-quadlet) · [podman run to Quadlet](#podman-run-to-quadlet) · [No direct equivalent](#no-direct-equivalent) · [podman generate systemd](#podman-generate-systemd) · [podlet](#podlet)

## Procedure

1. Resolve the source fully first: Compose interpolation (`${VAR:-default}`), `.env` files, `extends`, profiles and override files; work from the effective configuration, which the user can print with `docker compose config` or `podman compose config` on the host.
2. Build the workflow's inventory (SKILL.md step 2) from it, one service at a time.
3. Map each service with the tables below, applying the skill's defaults wherever the source is silent or unsafe: pin `:latest`, bind published ports to loopback unless exposure is intended, move inline secrets to Podman secrets.
4. Replace the Compose default network with one `.network` for the project, and named volumes with `.volume` files.
5. List every source setting that was dropped or changed, and why, in the report.

## Compose to Quadlet

| Compose | Quadlet |
|---|---|
| service name | file basename, `ContainerName=` |
| `image` | `Image=` (fully qualified, pinned) |
| `build` | a `.build` unit and `Image=x.build` |
| `command` | `Exec=` |
| `entrypoint` | `Entrypoint=` |
| `environment` | `Environment=` |
| `env_file` | `EnvironmentFile=` |
| `ports` | `PublishPort=` |
| `expose` | nothing (members of a `.network` reach container ports directly) |
| `volumes` (named) | `x.volume` file and `Volume=x.volume:/path` |
| `volumes` (bind) | `Volume=/host/path:/path[:ro]` |
| `tmpfs` | `Tmpfs=` |
| `networks` | `x.network` file and `Network=x.network` |
| `network_mode: host` / `none` | `Network=host` / `Network=none` |
| `network_mode: service:x` | `Network=x.container` |
| `aliases` | `NetworkAlias=` |
| `depends_on` | `[Unit] After=x.service` plus `Wants=x.service`, or `Requires=x.service` when the dependent cannot work without it (it also propagates stops and restarts); 5.4.2 names; report the semantic change |
| `depends_on: condition: service_healthy` | the same, plus `HealthCmd=` and `Notify=healthy` on the dependency |
| `healthcheck` | `HealthCmd=`, `HealthInterval=`, `HealthTimeout=`, `HealthRetries=`, `HealthStartPeriod=` |
| `restart: no` / `on-failure` / `always` | `[Service] Restart=no` / `Restart=on-failure` / `Restart=always` |
| `restart: unless-stopped` | `[Service] Restart=always`; systemd has no memory of a manual stop across reboots, so report the difference |
| no `restart` | the skill default `Restart=on-failure`, reported as a change |
| `secrets` | Podman secret and `Secret=` |
| `user` | `User=` / `Group=` |
| `working_dir` | `WorkingDir=` |
| `hostname` | `HostName=` |
| `extra_hosts` | `AddHost=` |
| `dns`, `dns_search`, `dns_opt` | `DNS=`, `DNSSearch=`, `DNSOption=` |
| `cap_add` / `cap_drop` | `AddCapability=` / `DropCapability=` |
| `read_only` | `ReadOnly=true` |
| `security_opt: no-new-privileges` | `NoNewPrivileges=true` |
| `devices` | `AddDevice=` |
| `sysctls` | `Sysctl=` |
| `ulimits` | `Ulimit=` |
| `shm_size` | `ShmSize=` |
| `init: true` | `RunInit=true` |
| `stop_signal` / `stop_grace_period` | `StopSignal=` / `StopTimeout=` |
| `labels` | `Label=` |
| `logging` | `LogDriver=` / `LogOpt=` only when the source needs a non-default driver |
| `mem_limit`, `cpus` | `[Service] MemoryMax=` / `CPUQuota=` (`cpus: 1.5` → `CPUQuota=150%`); `[Container] Memory=` from 5.5 |
| `privileged: true` | `PodmanArgs=--privileged`, only with the user's explicit confirmation |
| `container_name` | `ContainerName=` (the skill's default is the basename anyway) |

## podman run to Quadlet

Most `podman run` flags map one-to-one onto the `[Container]` key of the same meaning: `--name` → `ContainerName=`, `-p` → `PublishPort=`, `-v` → `Volume=`, `--mount` → `Mount=`, `-e` → `Environment=`, `--env-file` → `EnvironmentFile=`, `--network` → `Network=`, `--secret` → `Secret=`, `--user` → `User=`/`Group=`, `--userns` → `UserNS=`, `--cap-add`/`--cap-drop` → `AddCapability=`/`DropCapability=`, `--health-*` → `Health*=`, `--init` → `RunInit=`, `--read-only` → `ReadOnly=`, `--device` → `AddDevice=`, `--label` → `Label=`, `--entrypoint` → `Entrypoint=`, arguments after the image → `Exec=`.

- Drop `-d`, `--rm`, `--replace` and `-it`: Quadlet chooses the run mode itself and already adds `--rm` and `--replace`.
- Drop `--restart`; use `[Service] Restart=`.
- A flag with no key in the host version's list goes into `PodmanArgs=` with a comment.

## No direct equivalent

- `profiles`: decide per profile which units to write, or ship optional units with `[Install]` in a drop-in.
- `scale`/`deploy.replicas`: a template (`worker@.container`) with one instance per replica.
- `deploy` resource and placement settings: map the limits as above, drop the rest.
- `depends_on: condition: service_completed_successfully`: make the dependency `Type=oneshot` with `RemainAfterExit=yes`.
- `links`, `external_links`: shared `.network` and container names.
- `configs`: bind-mount the file read-only, or a Podman secret for sensitive content.
- Compose project-wide `name` and its container name prefixes: replaced by the basename names.

## podman generate systemd

- `podman generate systemd` is deprecated in favour of Quadlet; its units wrap one existing container with `podman start`/`stop` or recreate it with a long `ExecStart`.
- Migrate by reading the `podman run` command from the unit's `ExecStart` (or `podman inspect` of the container on the host) and converting it as above; remove the old unit file and disable it before starting the Quadlet one, since both may claim the same container name.

## podlet

- podlet (`github.com/containers/podlet`) converts `podman run` commands and Compose files to Quadlet files.
- It is optional and runs on the user's machine; treat its output as a draft and run it through this skill's defaults and review checklist.
- It does not support every Compose option or interpolation, and its version targets can lag behind the host's Podman.
