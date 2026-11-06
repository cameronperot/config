#!/usr/bin/python3 -I
"""Run an interactive terminal application in Bubblewrap with pasta networking.

Tier: compromised application. The application keeps the host terminal, so the
masked TIOCSTI/TIOCLINUX seccomp filter is mandatory and dev.tty.legacy_tiocsti
must be 0 where the sysctl exists.

Usage: example-interactive.py [--dry-run] [--exec -- CMD...] [--] [APP_ARGS...]

Access table:
    /usr, /etc               ro      host system, libraries, configuration
    /bin /sbin /lib*         link    mirrored from the host
    project root             rw      Git toplevel of $PWD, else $PWD; validated
    project .git             ro      when present, bound by descriptor; symlink refused
    ~/.local/bin/<app>       ro      the application binary
    ~/.example-agent         rw      persistent, from ~/.local/share/<STORE>
    $HOME /tmp /run          tmpfs   ephemeral
    /etc/resolv.conf target  ro      generated, names pasta's DNS forwarder
    network                  pasta   outbound only; no host loopback, no inbound
    EXAMPLE_API_KEY          env     forwarded through --args, redacted

Residual risks: exfiltration of the project over the network; edits to project
files the host later runs (Makefile, .envrc, .venv), and a planted .git in a
project that had none; kill(0) reaching the launcher's own process group; pasta
does not forward signals, and on Fedora SELinux denies its parent-death signal
to bwrap, so killing pasta alone can leave the sandbox running without network;
pasta failing before its command starts leaves a per-launch directory, removed
by the next launch; Fedora's pasta SELinux policy passing the terminal through
is unverified; kernel vulnerabilities.
"""

import contextlib
import errno
import os
import re
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path
from typing import BinaryIO

BWRAP = "/usr/bin/bwrap"
PASTA = "/usr/bin/pasta"
GIT = "/usr/bin/git"
APP = ".local/bin/example-agent"
STORE = ".local/share/example-agent-sandbox"
STATE = ".example-agent"
MIN_BWRAP = (0, 12, 0)
STALE_AFTER = 60.0
DNS_FORWARD = "169.254.1.1"
LEGACY_TIOCSTI = Path("/proc/sys/dev/tty/legacy_tiocsti")
FORWARDED_ENV = ("TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
SECRET_ENV = ("EXAMPLE_API_KEY",)
SYSTEM_TREES = tuple(
    Path(path)
    for path in (
        "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/opt", "/var", "/boot",
        "/root", "/srv", "/tmp", "/run", "/proc", "/sys", "/dev",
    )
)  # fmt: skip
# Runs after pasta, which closes inherited descriptors above 2: opens the host-only
# files as descriptors 3-5 and deletes them, opens the project's .git without
# following a symlink as descriptor 6 for --ro-bind-fd, then execs bwrap
STAGE = """
import os, stat, sys
*paths, git = sys.argv[1:5]
opened = [os.open(path, os.O_RDONLY) for path in paths]
for path in paths:
    os.unlink(path)
os.rmdir(os.path.dirname(paths[0]))
if git:
    pinned = os.open(git, os.O_PATH | os.O_NOFOLLOW)
    if stat.S_ISLNK(os.fstat(pinned).st_mode):
        sys.exit(f"{git} became a symlink; inspect it before launching")
    opened.append(pinned)
# Move each descriptor above the targets first, so dup2 never maps onto itself
moved = [os.dup(fd) for fd in opened]
for target, fd in zip((3, 4, 5, 6), moved):
    os.dup2(fd, target)
os.execv(sys.argv[5], sys.argv[5:])
"""

# Flatpak 1.18.4's non-devel baseline plus every clone namespace flag
EPERM_SYSCALLS = (
    "syslog", "uselib", "acct", "quotactl", "add_key", "keyctl", "request_key",
    "move_pages", "mbind", "get_mempolicy", "set_mempolicy", "migrate_pages",
    "unshare", "setns", "mount", "umount", "umount2", "pivot_root", "chroot",
    "modify_ldt", "perf_event_open", "ptrace",
)  # fmt: skip
ENOSYS_SYSCALLS = (
    "clone3", "open_tree", "move_mount", "fsopen", "fsconfig", "fsmount", "fspick",
    "mount_setattr",
)  # fmt: skip
CLONE_NAMESPACES = (
    os.CLONE_NEWNS, os.CLONE_NEWCGROUP, os.CLONE_NEWUTS, os.CLONE_NEWIPC,
    os.CLONE_NEWUSER, os.CLONE_NEWPID, os.CLONE_NEWNET,
)  # fmt: skip
SOCKET_FAMILIES = (
    socket.AF_UNSPEC, socket.AF_UNIX, socket.AF_INET, socket.AF_INET6,
    socket.AF_NETLINK,
)  # fmt: skip


class SandboxError(Exception):
    """An expected launch failure, reported without a traceback."""


def preflight(options: list[str]) -> None:
    """Check tools, the bwrap version, every option used, and terminal protection.

    Args:
        options: bwrap's options without environment values, which may hold
            secrets; each option token must appear in bwrap --help.

    Raises:
        SandboxError: When any prerequisite is missing.
    """
    for tool in (BWRAP, PASTA, GIT):
        if not os.access(tool, os.X_OK):
            raise SandboxError(f"{tool} not found; install bubblewrap, passt and git")
    run = {"capture_output": True, "text": True, "check": True}
    version = subprocess.run((BWRAP, "--version"), **run).stdout.strip()
    match = re.fullmatch(r"bubblewrap (\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise SandboxError(f"cannot parse bwrap version {version!r}")
    if tuple(map(int, match.groups())) < MIN_BWRAP:
        raise SandboxError(f"{version} is older than 0.12.0")
    usage = subprocess.run((BWRAP, "--help"), **run).stdout
    tokens = {
        arg for arg in ("--args", *options) if re.fullmatch(r"--[a-z][a-z0-9-]*", arg)
    }
    missing = sorted(token for token in tokens if f"{token} " not in usage)
    if missing:
        raise SandboxError(f"bwrap lacks {', '.join(missing)}")
    if LEGACY_TIOCSTI.exists() and LEGACY_TIOCSTI.read_text().strip() != "0":
        raise SandboxError("dev.tty.legacy_tiocsti is not 0; set it on the host first")


def project_root(cwd: Path) -> Path:
    """Return the Git toplevel of the working directory, else the directory itself.

    Args:
        cwd: The resolved working directory.

    Returns:
        The resolved project root.
    """
    result = subprocess.run(
        (GIT, "-C", str(cwd), "rev-parse", "--show-toplevel"),
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else cwd


def check_root(root: Path, *, home: Path, protected: tuple[Path, ...]) -> None:
    """Reject writable roots that would expose or endanger host state.

    Args:
        root: The resolved candidate root.
        home: The resolved home directory.
        protected: Paths the sandbox must not write.

    Raises:
        SandboxError: When the root is forbidden.
    """
    if root == Path("/") or home.is_relative_to(root):
        raise SandboxError(f"{root} is / or contains the home directory")
    if any(root.is_relative_to(tree) for tree in SYSTEM_TREES):
        raise SandboxError(f"{root} is inside a system tree")
    if root.is_relative_to(home) and root.relative_to(home).parts[0].startswith("."):
        raise SandboxError(f"{root} is under a hidden entry of the home directory")
    if any(
        root.is_relative_to(path) or path.is_relative_to(root) for path in protected
    ):
        raise SandboxError(f"{root} overlaps a protected path")


def build_seccomp(file: BinaryIO) -> None:
    """Write the baseline seccomp program with the masked terminal-ioctl rules.

    Args:
        file: The binary file the BPF program is written to.

    Raises:
        SandboxError: When the bindings are missing or the program cannot be built.
    """
    try:
        import seccomp
    except ImportError:
        raise SandboxError(
            "install libseccomp-python (Fedora) or python3-seccomp (Debian)"
        ) from None
    eperm = seccomp.ERRNO(errno.EPERM)
    bpf = seccomp.SyscallFilter(seccomp.ALLOW)
    for name in EPERM_SYSCALLS:
        bpf.add_rule(eperm, name)
    for name in ENOSYS_SYSCALLS:
        bpf.add_rule(seccomp.ERRNO(errno.ENOSYS), name)
    for flag in CLONE_NAMESPACES:
        bpf.add_rule(eperm, "clone", seccomp.Arg(0, seccomp.MASKED_EQ, flag, flag))
    # The kernel reads only the low 32 bits of the request (CVE-2019-10063)
    for request in (termios.TIOCSTI, termios.TIOCLINUX):
        bpf.add_rule(
            eperm, "ioctl", seccomp.Arg(1, seccomp.MASKED_EQ, 0xFFFFFFFF, request)
        )
    bpf.add_rule(eperm, "personality", seccomp.Arg(0, seccomp.NE, 0))
    eafnosupport = seccomp.ERRNO(errno.EAFNOSUPPORT)
    for family in range(max(SOCKET_FAMILIES)):
        if family not in SOCKET_FAMILIES:
            bpf.add_rule_exactly(
                eafnosupport, "socket", seccomp.Arg(0, seccomp.EQ, family)
            )
    bpf.add_rule_exactly(
        eafnosupport, "socket", seccomp.Arg(0, seccomp.GE, max(SOCKET_FAMILIES) + 1)
    )
    bpf.export_bpf(file)


def top_level_links() -> list[str]:
    """Mirror the host's /bin, /lib and similar entries.

    Returns:
        bwrap options recreating each existing entry.
    """
    args: list[str] = []
    for top in ("/bin", "/sbin", "/lib", "/lib64", "/lib32", "/libx32"):
        if os.path.islink(top):
            args += ("--symlink", os.readlink(top), top)
        elif os.path.isdir(top):
            args += ("--ro-bind", top, top)
    return args


def bwrap_options(*, home: Path, root: Path, cwd: Path) -> list[str]:
    """Build bwrap's path policy in mount order, without environment options.

    Called once per launch: the result decides whether the stage pins .git, so a
    second evaluation could disagree with it.

    Args:
        home: The resolved home directory.
        root: The validated writable project root.
        cwd: The resolved working directory.

    Returns:
        The options; descriptors 4 (seccomp), 5 (resolv.conf) and 6 (.git, when
        pinned) come from the stage.

    Raises:
        SandboxError: When the project's .git is a symlink.
    """
    uid, gid = str(os.getuid()), str(os.getgid())
    resolv = Path("/etc/resolv.conf").resolve()
    args = [
        "--unshare-all", "--share-net", "--unshare-user", "--uid", uid, "--gid", gid,
        "--disable-userns", "--cap-drop", "ALL", "--die-with-parent", "--clearenv",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc", *top_level_links(),
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
        "--perms", "0700", "--dir", f"/run/user/{uid}", "--tmpfs", str(home),
        "--ro-bind", str((home / APP).resolve()), str(home / APP),
        "--bind", str(home / STORE / "state"), str(home / STATE),
        "--bind", str(root), str(root),
    ]  # fmt: skip
    git = root / ".git"
    # The project is writable, so .git may be a symlink planted by an earlier run;
    # the stage re-checks it and binds the descriptor it opened, closing the race
    if git.is_symlink():
        raise SandboxError(f"{git} is a symlink; inspect it before launching")
    if git.exists():
        args += ("--ro-bind-fd", "6", str(git))
    for parent in reversed(resolv.parents):
        if parent.is_relative_to("/run") and parent != Path("/run"):
            args += ("--dir", str(parent))
    args += ("--ro-bind-data", "5", str(resolv))
    return [*args, "--seccomp", "4", "--chdir", str(cwd)]


def redact(args: list[str]) -> list[str]:
    """Replace secret --setenv values for display.

    Args:
        args: bwrap options.

    Returns:
        A copy with each secret value replaced by "<redacted>".
    """
    shown = list(args)
    for index, arg in enumerate(shown[:-2]):
        if arg == "--setenv" and shown[index + 1] in SECRET_ENV:
            shown[index + 2] = "<redacted>"
    return shown


def ensure_owned_dirs(base: Path, relative: str) -> Path:
    """Create relative under base, refusing symlinked or foreign components.

    Args:
        base: An existing trusted directory, such as the home directory.
        relative: The path to create below it.

    Returns:
        The created or existing directory.

    Raises:
        SandboxError: When a component is a symlink, not a directory, or not owned
            by the invoking user.
    """
    path = base
    for part in Path(relative).parts:
        path = path / part
        with contextlib.suppress(FileExistsError):
            path.mkdir(mode=0o700)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise SandboxError(f"{path} is not a directory owned by you")
    return path


def private_dir() -> Path:
    """Create a per-launch mode-0700 directory under a validated runtime directory.

    Leftovers older than STALE_AFTER, from a pasta that failed before running the
    stage, are removed first.

    Returns:
        The new directory.

    Raises:
        SandboxError: When XDG_RUNTIME_DIR is unset or not private to the user.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        raise SandboxError("XDG_RUNTIME_DIR is not set")
    info = os.lstat(runtime_dir)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise SandboxError(f"{runtime_dir} is not a mode-0700 directory owned by you")
    parent = ensure_owned_dirs(Path(runtime_dir), "example-agent-sandbox")
    for leftover in parent.iterdir():
        if time.time() - leftover.lstat().st_mtime > STALE_AFTER:
            for file in leftover.iterdir():
                file.unlink()
            leftover.rmdir()
    return Path(tempfile.mkdtemp(dir=parent))


def write_private(directory: Path, data: bytes) -> str:
    """Write data to a new mode-0600 file in a host-only directory.

    Args:
        directory: The mode-0700 directory.
        data: The content.

    Returns:
        The file's path.
    """
    fd, path = tempfile.mkstemp(dir=directory)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
    return path


def launch(
    *, prefix: list[str], options: list[str], git: str, command: list[str]
) -> None:
    """Write the host-only files the stage opens, then exec pasta.

    Args:
        prefix: The pasta and stage argv, up to the stage's file arguments.
        options: bwrap's options, secrets included.
        git: The .git path the stage opens for --ro-bind-fd, or "" for none.
        command: The command bwrap runs after "--".

    Raises:
        SandboxError: When the runtime directory is unsafe or the filter fails.
        OSError: When a file cannot be written or pasta cannot be executed.
    """
    directory = private_dir()
    files: list[str] = []
    try:
        files.append(
            write_private(directory, b"".join(f"{a}\0".encode() for a in options))
        )
        files.append(write_private(directory, b""))
        with open(files[1], "wb") as file:
            build_seccomp(file)
        files.append(write_private(directory, f"nameserver {DNS_FORWARD}\n".encode()))
        # Inherited descriptors would bypass the mount and network policy
        os.closerange(3, os.sysconf("SC_OPEN_MAX"))
        argv = [*prefix, *files, git, BWRAP, "--args", "3", "--", *command]
        os.execv(PASTA, argv)
    finally:
        # Reached only when exec failed; on success the stage deletes the files
        for path in files:
            Path(path).unlink(missing_ok=True)
        directory.rmdir()


def main(argv: list[str]) -> int:
    """Validate, build the policy, and launch or print it.

    Args:
        argv: The wrapper's arguments.

    Returns:
        The exit status on a dry run or failure; a real launch does not return.
    """
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    dry_run = argv[:1] == ["--dry-run"]
    argv = argv[1:] if dry_run else argv
    home, cwd = Path.home().resolve(), Path.cwd().resolve()
    if argv[:2] == ["--exec", "--"] and len(argv) > 2:
        command = argv[2:]
    else:
        command = [str(home / APP), *(argv[1:] if argv[:1] == ["--"] else argv)]
    try:
        if not os.access(command[0], os.X_OK) or not os.access(home / APP, os.X_OK):
            raise SandboxError(f"{command[0]} or {home / APP} is not executable")
        root = project_root(cwd)
        lexical = (home / STORE, home / APP, Path(__file__).absolute())
        protected = (*lexical, *(path.resolve() for path in lexical))
        check_root(root, home=home, protected=protected)
        wanted = (*FORWARDED_ENV, *SECRET_ENV)
        env = {key: os.environ[key] for key in wanted if os.environ.get(key)}
        env |= {
            "HOME": str(home),
            "PATH": f"{home}/.local/bin:/usr/bin:/bin",
            "SHELL": "/bin/bash",
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
        }
        # Env values may hold secrets or option-like strings, so preflight and the
        # .git decision use the path policy alone
        static = bwrap_options(home=home, root=root, cwd=cwd)
        preflight([*static, "--setenv"])
        with tempfile.TemporaryFile() as scratch:
            build_seccomp(scratch)
        setenv = [arg for item in env.items() for arg in ("--setenv", *item)]
        options = [*static, *setenv]
        prefix = [
            PASTA, "--config-net", "-t", "none", "-u", "none", "-T", "none",
            "-U", "none", "--no-map-gw", "--dns-forward", DNS_FORWARD, "--",
            "/usr/bin/python3", "-I", "-c", STAGE,
        ]  # fmt: skip
        git = str(root / ".git") if "--ro-bind-fd" in static else ""
        if dry_run:
            files = ["<args-file>", "<seccomp-file>", "<resolv-file>", git]
            shown = [*prefix, *files, BWRAP, *redact(options), "--", *command]
            print(shlex.join(shown))
            return 0
        ensure_owned_dirs(home, f"{STORE}/state")
        launch(prefix=prefix, options=options, git=git, command=command)
    except (SandboxError, OSError, subprocess.CalledProcessError) as exc:
        print(f"{Path(sys.argv[0]).name}: error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
