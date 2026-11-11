# Versions

Contents: [Baseline](#baseline) · [Additions after 5.4.2](#additions-after-542) · [Podman 6.0 breaking changes](#podman-60-breaking-changes) · [Versioned documentation](#versioned-documentation)

Compatibility notes cover Podman 5.4.2 through 6.1, checked against the upstream release notes and versioned man pages.

## Baseline

- The skill's baseline is Podman 5.4.2: every key in the 5.4.2 lists in [container.md](container.md#keys-in-542) and [resources.md](resources.md) is safe to use.
- 5.4.2 already has `.pod`, `.build`, `.image`, templates, drop-ins (including type-wide and dash-prefix directories), `Notify=healthy`, `[Quadlet] DefaultDependencies=`, `podman-user-wait-network-online.service`, pasta as the rootless default network, and `/run/containers/systemd/`.
- Use a key from the table below only when the host version is known to be at least the listed one, and confirm the key in that version's man page; the 5.5–5.7 rows come from release notes and are less precise than the 5.4.2 key lists.

## Additions after 5.4.2

| Podman | Additions |
|---|---|
| 5.5 | `[Unit]` dependencies may name Quadlet files (`After=db.container`); stopping a `.network` unit removes the network when unused; `[Container] Memory=`, `ReloadCmd=`, `ReloadSignal=`; `Retry=`/`RetryDelay=` for container, image and build pulls; `[Pod] HostName=`; `[Install] UpheldBy=` |
| 5.6 | `podman quadlet install/list/print/rm`; `Environment=` entries without values; `[Pod] Label=`, `ExitPolicy=`; `[Image] Policy=`; `[Network] InterfaceName=` |
| 5.7 | `.artifact` units (experimental); `[Container] HttpProxy=`; `[Pod] StopTimeout=`; `[Build] BuildArg=`, `IgnoreFile=`; multi-document `.kube` YAML; templated `.volume`/`.network` references; `podman quadlet install --replace`, `print` alias `cat` |
| 5.8 | Multi-unit `.quadlets` install files; `[Container] AppArmor=` |
| 6.0 | Per-type man pages; `[Volume] UID=`, `GID=`; `Mount=` without a source creates an anonymous volume; `/usr/share/containers/systemd/users/` search paths; `podman quadlet list` alias `ls`, `--noheading`, `Pod` column, `--filter status=`; `.pod` services honour the user's `Restart=`; installed applications tracked in subdirectories instead of `.app` files |
| 6.1 | `[Container] ImageVolume=`; generator errors on stderr, so `systemd-analyze --generators=true verify` shows them; fixes for template handling in `podman quadlet list`/`rm` and a race that could generate corrupt units |

`[Network] NetworkDeleteOnStop=` and `[Quadlet] SetMountsDependency=` exist in later versions without a confirmed introduction version; check the versioned man page before using them.

## Podman 6.0 breaking changes

Relevant to Quadlet hosts:

- cgroup v1, CNI, slirp4netns and iptables support are removed: networks use netavark with nftables, and pasta is the only user-mode rootless network (rootless user-defined `.network` bridges still work).
- Network isolation is on by default.
- The `podman quadlet` command family changed how it tracks installed files.

## Versioned documentation

- Quadlet keys: `https://docs.podman.io/en/v<version>/markdown/podman-systemd.unit.5.html`; from 6.0 the per-type pages `podman-container.unit.5.html`, `podman-network.unit.5.html`, `podman-volume.unit.5.html`, `podman-pod.unit.5.html`, `podman-image.unit.5.html`, `podman-build.unit.5.html`, `podman-kube.unit.5.html`.
- Option semantics behind a key: `podman-run.1.html`, `podman-network-create.1.html`, `podman-volume-create.1.html`, `podman-auto-update.1.html`, `podman-secret-create.1.html` under the same versioned prefix.
- Release history for a version: `https://github.com/containers/podman/releases/tag/v<version>`.
- Never use `/en/latest/`, which documents the development branch.
