# Resource units

Contents: [Network](#network) · [Volume](#volume) · [Pod](#pod) · [Image](#image) · [Build](#build) · [Kube](#kube) · [Artifact](#artifact)

Key lists are the complete sets in Podman 5.4.2; anything else needs a newer host ([versions.md](versions.md)) or `PodmanArgs=`.

## Network

Keys: ContainersConfModule, DisableDNS, DNS, Driver, Gateway, GlobalArgs, Internal, IPAMDriver, IPRange, IPv6, Label, NetworkName, Options, PodmanArgs, Subnet.

- One `.network` per group of containers that talk to each other; each member says `Network=app.network`.
- `Driver=` defaults to `bridge` with DNS on (`DisableDNS=false`), which is what gives containers name resolution.
- `Subnet=`, `Gateway=` and `IPRange=` are needed only for fixed addressing or to avoid a clash with another network on the host; leave them out otherwise.
- `Internal=true` cuts the network off from the outside, for back-end tiers that must not reach the internet.
- `IPv6=true` with an IPv6 `Subnet=` adds dual-stack.
- `macvlan`/`ipvlan` drivers put containers on the host's LAN, which rootless networking does not support for port forwarding; treat them as a rootful choice.
- The network is created on first start and, on 5.4.2, kept afterwards; changing the file does not change it (see [lifecycle.md](lifecycle.md#changing-and-removing-units)).
- No `[Install]` section: the containers that reference it pull it in.

## Volume

Keys: ContainersConfModule, Copy, Device, Driver, GlobalArgs, Group, Image, Label, Options, PodmanArgs, Type, User, VolumeName.

- One `.volume` per piece of app-owned state, mounted with `Volume=pgdata.volume:/var/lib/postgresql/data`.
- `Copy=true` (default) copies the image's content at the mount point into the volume on first use, so image-provided defaults appear in a fresh volume.
- `Device=`, `Type=` and `Options=` mount external storage through the local driver, for example NFS: `Type=nfs`, `Device=server:/export`, `Options=addr=…,nfsvers=4`.
- `Driver=image` with `Image=` creates a volume from an image's content.
- `User=` and `Group=` are passed to the volume's mount; read the 5.4.2 man page before relying on them for ownership (Podman 6.0 adds `UID=`/`GID=` for that).
- Volumes are never deleted by Quadlet; deletion is an explicit `podman volume rm` with data loss (rule 9).
- No `[Install]` section.

## Pod

Keys: AddHost, ContainersConfModule, DNS, DNSOption, DNSSearch, GIDMap, GlobalArgs, IP, IP6, Network, NetworkAlias, PodmanArgs, PodName, PublishPort, ServiceName, ShmSize, SubGIDMap, SubUIDMap, UIDMap, UserNS, Volume.

- Use a pod only when containers must share one network namespace (talking over `localhost`), IPC, or a single start-stop lifecycle; otherwise use a `.network` with separate containers, which restart independently.
- Members declare `Pod=stack.pod` and need basenames distinct from the pod's name (`stack-web.container`, `stack-db.container`), because pods and containers share a name space.
- Ports, networks, user namespace and extra hosts belong on the `.pod`; members must not set `PublishPort=` or `Network=`.
- `[Container] StartWithPod=` (default `true`) starts the member with the pod; `false` leaves it to be started on its own but still stopped with the pod.
- Before Podman 6.0, Quadlet sets `Restart=on-failure` on the pod service regardless of the user's `Restart=`, and 5.4.2 has no `ExitPolicy=` key; rely on per-member `Restart=` for recovery.
- Pod-level resource limits apply to members only when they set `CgroupsMode=no-conmon` or `enabled`.

## Image

Keys: AllTags, Arch, AuthFile, CertDir, ContainersConfModule, Creds, DecryptionKey, GlobalArgs, Image, ImageTag, OS, PodmanArgs, TLSVerify, Variant.

- A `.image` pulls once as a `oneshot` before its dependents start; a container uses it with `Image=api.image`.
- Use it for private registries (`AuthFile=` pointing at a persistent credentials file, see [operations.md](operations.md#private-registries)) and to keep a slow pull out of the container's start timeout.
- Avoid `Creds=`, which puts the password in the unit file.
- `ImageTag=` matters only for archive sources (`Image=docker-archive:/path.tar`), where it names the loaded image.
- A `oneshot` has no start timeout by default; set `TimeoutStartSec=` in `[Service]` when a hung pull must fail.

## Build

Keys: Annotation, Arch, AuthFile, ContainersConfModule, DNS, DNSOption, DNSSearch, Environment, File, ForceRM, GlobalArgs, GroupAdd, ImageTag, Label, Network, PodmanArgs, Pull, Secret, SetWorkingDirectory, Target, TLSVerify, Variant, Volume.

- `ImageTag=` is required; the first one is the image a container gets with `Image=api.build`.
- Give the build context with `SetWorkingDirectory=` (`unit` for the Quadlet file's directory, a path, or a Git/archive URL) and the Containerfile with `File=`.
- The build runs when `api-build.service` starts, not on daemon-reload; rebuild with `systemctl --user restart api-build.service` and then restart the containers.
- `Environment=` sets environment in the built image; build arguments need `PodmanArgs=--build-arg=KEY=value` on 5.4.2 (`BuildArg=` arrives in 5.7).
- `Secret=` passes build secrets without baking them into layers.

## Kube

Keys: AutoUpdate, ConfigMap, ContainersConfModule, ExitCodePropagation, GlobalArgs, KubeDownForce, LogDriver, Network, PodmanArgs, PublishPort, SetWorkingDirectory, UserNS, Yaml.

- A `.kube` runs `podman kube play` on Kubernetes YAML (`Yaml=./site.yaml`, required) as one service; use it when the workload already exists as Kubernetes YAML, not as the default for new work.
- Readiness, names, secrets and ports then come from the YAML; read `podman-systemd.unit(5)` (Kube section) and `podman-kube-play(1)` for the host version before writing one.
- Do not manage the same workload with both `.kube` and `.container` files.
- Do not set `AutoUpdate=` on a `.kube`: it cannot carry the `HealthCmd=` + `Notify=healthy` gating this skill requires for auto-update.

## Artifact

- `.artifact` (Podman 5.7+, marked experimental) pulls an OCI artifact for containers to mount with `Mount=type=artifact,source=x.artifact,destination=/path`.
- It does not exist on 5.4.2; read the man page for the host version before using it.
