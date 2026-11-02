r"""Host-only escape probes for dotfiles/bin/vscode-sandbox (AC2-AC4, AC6, AC7).

Run on the Fedora host, with no VS Code running, from the repository root:

    VSCODE_SANDBOX_PROBES=1 /usr/bin/python3 -m pytest --noconftest \
        -p no:cacheprovider -o addopts= tests/test_vscode_sandbox_probes.py

Each test runs run_sandbox(..., detach=False) in a dedicated driver subprocess, since
the supervisor kills every child it owns once the sandbox ends. Host helpers (the
sentinel sleep, listeners, sentinel descriptors) live in the test process. The probe
runs in the sandbox as /usr/bin/python3 -I <root>/probe.py <check>, reads its
arguments from <root>/args.json and writes its result to <root>/result.json. Only the
standard library and pytest are used, so the suite runs on the host's Python.
"""

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("VSCODE_SANDBOX_PROBES") != "1":
    pytest.skip(
        "host probes run only with VSCODE_SANDBOX_PROBES=1", allow_module_level=True
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "dotfiles" / "bin" / "vscode-sandbox"
# The script's own interpreter, which has the seccomp bindings
HOST_PYTHON = "/usr/bin/python3"
LAUNCH_TIMEOUT = 120.0
TOKEN = "vscode-sandbox-probe-token"
# Longer than pasta's interval between scans for automatic port forwarding
INBOUND_WINDOW = 3.0


def load_script():
    """Import the executable without creating bytecode files next to it."""
    loader = SourceFileLoader("vscode_sandbox", str(SCRIPT))
    spec = importlib.util.spec_from_loader("vscode_sandbox", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module


sandbox = load_script()
HOME = Path.home().resolve()
CODE_LOG = HOME / sandbox.STORE / "code.log"

# Runs as the supervisor: argv is the script path and a JSON launch spec; prints the
# outcome as JSON. start_guard is wrapped to record whether the launch got that far
DRIVER = r"""
import importlib.util
import json
import os
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

script, spec = Path(sys.argv[1]), json.loads(sys.argv[2])
report = os.fdopen(os.dup(1), "w")
if spec["terminal"]:
    # The launcher's stdio are a terminal, as when started from a shell
    terminal, terminal_peer = os.openpty()
    for fd in (0, 1, 2):
        os.dup2(terminal_peer, fd)
loader = SourceFileLoader("vscode_sandbox", str(script))
sandbox = importlib.util.module_from_spec(
    importlib.util.spec_from_loader(loader.name, loader)
)
loader.exec_module(sandbox)
for name, value in spec["constants"].items():
    setattr(sandbox, name, value)
sandbox.WAYLAND_GLOBALS -= frozenset(spec["omit_globals"])

spawned = []
start_guard = sandbox.start_guard


def recording_start_guard(*args, **kwargs):
    spawned.append(True)
    if not spec["spawn"]:
        raise sandbox.SandboxError("the launch reached start_guard")
    return start_guard(*args, **kwargs)


sandbox.start_guard = recording_start_guard
env = sandbox.host_env(os.environ)
root = Path(spec["root"])
config = sandbox.resolve_config(
    sandbox.parse_args(
        [str(root), *(f"--port={port}" for port in spec["ports"]), *spec["options"]]
    ),
    home=sandbox.resolve_path(Path(env["HOME"])),
    cwd=root,
    script=script.resolve(),
    state_dir=Path(env["XDG_RUNTIME_DIR"], sandbox.STATE_DIR),
)
try:
    status = sandbox.run_sandbox(config, spec["command"], env=env, detach=False)
    outcome = {"status": status}
except sandbox.SandboxError as error:
    outcome = {"error": str(error)}
outcome["spawned"] = bool(spawned)
print(json.dumps(outcome), file=report)
"""

# Runs inside the sandbox; x86_64 only, as is the host
PROBE = r'''
"""vscode-sandbox escape probe: /usr/bin/python3 -I probe.py <check>."""

import ctypes
import errno
import fcntl
import json
import os
import signal
import socket
import struct
import sys
import termios
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).parent
SYSCALLS = {
    "ioctl": 16,
    "socket": 41,
    "clone": 56,
    "ptrace": 101,
    "personality": 135,
    "add_key": 248,
    "fsopen": 430,
    "clone3": 435,
}
PTRACE_TRACEME = 0
PER_LINUX32 = 0x0008
KEY_SPEC_PROCESS_KEYRING = -2

libc = ctypes.CDLL(None, use_errno=True)
# 64-bit arguments, so a request such as TIOCSTI | 1 << 32 is not truncated
libc.syscall.restype = ctypes.c_long
libc.syscall.argtypes = (ctypes.c_long,) * 6


def error_name(error):
    if error.errno is None:
        return type(error).__name__
    return errno.errorcode.get(error.errno, str(error.errno))


def attempt(function, *args):
    try:
        function(*args)
    except OSError as error:
        return error_name(error)
    return "ok"


def exists(path):
    return os.path.lexists(path)


def environment(name):
    return name in os.environ


def write(path):
    # An existing file is opened for appending without writing; anything created is
    # removed again
    path = Path(path)
    created = path.is_dir() or not path.exists()
    target = path / f"vscode-sandbox-probe-{os.getpid()}" if path.is_dir() else path
    flags = os.O_WRONLY | (os.O_CREAT | os.O_EXCL if created else os.O_APPEND)
    try:
        os.close(os.open(target, flags, 0o600))
    except OSError as error:
        return error_name(error)
    if created:
        target.unlink()
    return "ok"


def create(path, content):
    # Left in place for the host to find at the bind source
    try:
        with open(path, "x") as file:
            file.write(content)
    except OSError as error:
        return error_name(error)
    return "ok"


def mounts():
    # Mount point fields, still escaped as mountinfo writes them
    lines = Path("/proc/self/mountinfo").read_text().splitlines()
    return [line.split()[4] for line in lines]


def dri():
    return sorted(os.listdir("/dev/dri")) if os.path.isdir("/dev/dri") else []


def wayland():
    path = Path(os.environ["XDG_RUNTIME_DIR"], os.environ["WAYLAND_DISPLAY"])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(str(path))
        # wl_display.get_registry(new_id 2), then wl_display.sync(new_id 3)
        sock.sendall(
            struct.pack("<III", 1, 12 << 16 | 1, 2)
            + struct.pack("<III", 1, 12 << 16 | 0, 3)
        )
        names = []
        buffer = b""
        while True:
            while len(buffer) < 8 or len(buffer) < buffer[6] | buffer[7] << 8:
                chunk = sock.recv(4096)
                if not chunk:
                    raise EOFError("the compositor closed the connection")
                buffer += chunk
            object_id, word = struct.unpack_from("<II", buffer)
            size, opcode = word >> 16, word & 0xFFFF
            body, buffer = buffer[8:size], buffer[size:]
            if object_id == 1 and opcode == 0:
                raise RuntimeError(f"wl_display.error: {body!r}")
            if object_id == 2 and opcode == 0:
                (length,) = struct.unpack_from("<I", body, 4)
                names.append(body[8 : 8 + length - 1].decode())
            if object_id == 3:
                return names


def stdin_tiocsti():
    return attempt(fcntl.ioctl, 0, termios.TIOCSTI, b"x")


def processes(token):
    scanned = 0
    matches = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        scanned += 1
        if token.encode() in cmdline:
            matches.append(int(entry.name))
    return {"scanned": scanned, "matches": matches}


def unshare(flag):
    return attempt(os.unshare, getattr(os, flag))


def seccomp():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("Seccomp:"):
            return line.split(":", 1)[1].strip()
    return None


def syscall(name):
    buffers = []

    def address(data):
        buffers.append(ctypes.create_string_buffer(data))
        return ctypes.addressof(buffers[-1])

    read_end, _ = os.pipe()
    calls = {
        "clone_newuser": ("clone", os.CLONE_NEWUSER | signal.SIGCHLD),
        "clone3": ("clone3", 0, 0),
        "fsopen": ("fsopen", address(b"tmpfs"), 0),
        "ptrace_traceme": ("ptrace", PTRACE_TRACEME),
        "add_key": (
            "add_key",
            address(b"user"),
            address(b"vscode-sandbox-probe"),
            address(b"x"),
            1,
            KEY_SPEC_PROCESS_KEYRING,
        ),
        "personality": ("personality", PER_LINUX32),
        "ioctl_tiocsti": ("ioctl", read_end, termios.TIOCSTI, address(b"x")),
        "ioctl_tiocsti_high": (
            "ioctl",
            read_end,
            termios.TIOCSTI | 1 << 32,
            address(b"x"),
        ),
        "socket_packet": ("socket", socket.AF_PACKET, socket.SOCK_RAW, 0),
    }
    syscall_name, *args = calls[name]
    ctypes.set_errno(0)
    result = libc.syscall(SYSCALLS[syscall_name], *args, *(0,) * (5 - len(args)))
    if result < 0:
        return errno.errorcode[ctypes.get_errno()]
    # The call was allowed; undo its effect
    if name == "clone_newuser":
        if result == 0:
            os._exit(0)
        os.waitpid(result, 0)
    elif name in ("fsopen", "socket_packet"):
        os.close(result)
    elif name == "personality":
        libc.syscall(SYSCALLS["personality"], 0, 0, 0, 0, 0)
    return "ok"


def fds():
    # The listing's own descriptor is closed again by the time it is checked
    names = os.listdir("/proc/self/fd")
    return sorted(name for name in names if os.path.exists(f"/proc/self/fd/{name}"))


def ttys():
    return [os.isatty(fd) for fd in (0, 1, 2)]


def internet(host, port):
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = sorted({info[4][0] for info in infos})
    errors = {}
    for family, kind, proto, _, address in infos:
        try:
            with socket.socket(family, kind, proto) as sock:
                sock.settimeout(10)
                sock.connect(address)
        except OSError as error:
            errors[address[0]] = error_name(error)
            continue
        return {"addresses": addresses, "connected": address[0], "errors": errors}
    return {"addresses": addresses, "connected": None, "errors": errors}


def gateway(name):
    if name == "@gateway4":
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            fields = line.split()
            # Destination 0.0.0.0 with RTF_GATEWAY
            if fields[1] == "00000000" and int(fields[3], 16) & 0x2:
                return socket.inet_ntoa(struct.pack("<I", int(fields[2], 16))), 0
        return None
    if not os.path.exists("/proc/net/ipv6_route"):
        return None
    for line in Path("/proc/net/ipv6_route").read_text().splitlines():
        fields = line.split()
        if fields[0] == "0" * 32 and fields[1] == "00" and fields[4] != "0" * 32:
            address = socket.inet_ntop(socket.AF_INET6, bytes.fromhex(fields[4]))
            link_local = address.startswith("fe80:")
            return address, socket.if_nametoindex(fields[9]) if link_local else 0
    return None


def reach(host, port):
    if host.startswith("@"):
        found = gateway(host)
        if found is None:
            return {"address": None, "received": None, "error": "no gateway"}
        host, scope = found
    else:
        scope = 0
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    address = (host, port, 0, scope) if family == socket.AF_INET6 else (host, port)
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(address)
            received = sock.recv(64).decode(errors="replace")
    except OSError as error:
        return {"address": host, "received": None, "error": error_name(error)}
    return {"address": host, "received": received, "error": None}


def connect(targets):
    return {label: reach(host, port) for label, (host, port) in targets.items()}


def inbound(token):
    accepted = []

    def serve(connection, peer):
        with connection:
            accepted.append(peer[0])
            connection.sendall(token.encode())

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("0.0.0.0", 0))
        server.listen()
        port = server.getsockname()[1]
        # The listener accepts from inside, so only the host side can be missing
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            server.accept()[0].close()
        (ROOT / "listening.tmp").write_text(json.dumps({"port": port}))
        os.replace(ROOT / "listening.tmp", ROOT / "listening.json")
        server.settimeout(0.2)
        deadline = time.monotonic() + 30
        while not (ROOT / "done").exists() and time.monotonic() < deadline:
            try:
                serve(*server.accept())
            except TimeoutError:
                continue
        # Connections still queued when done appeared
        server.setblocking(False)
        while True:
            try:
                serve(*server.accept())
            except BlockingIOError:
                break
    return {"accepted": accepted, "done": (ROOT / "done").exists()}


def abstract(name):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        return attempt(sock.connect, "\0" + name)


CHECKS = {
    function.__name__: function
    for function in (
        exists,
        environment,
        write,
        create,
        mounts,
        dri,
        wayland,
        stdin_tiocsti,
        processes,
        unshare,
        seccomp,
        syscall,
        fds,
        ttys,
        internet,
        connect,
        inbound,
        abstract,
    )
}

args = json.loads((ROOT / "args.json").read_text())
try:
    result = {"value": CHECKS[sys.argv[1]](**args)}
except Exception:
    result = {"exception": traceback.format_exc()}
(ROOT / "result.json").write_text(json.dumps(result))
'''


def log_tail() -> str:
    """
    Read the end of the sandbox log, for failure messages.

    :return: The last 4000 characters of code.log.
    """
    return CODE_LOG.read_text(errors="replace")[-4000:]


def start(
    root: Path,
    check: str,
    args: Mapping[str, Any] | None = None,
    *,
    ports: Sequence[int] = (),
    options: Sequence[str] = (),
    constants: Mapping[str, str] | None = None,
    omit_globals: Sequence[str] = (),
    spawn: bool = True,
    pass_fds: Sequence[int] = (),
    terminal: bool = False,
) -> subprocess.Popen[str]:
    """
    Start a driver subprocess that runs one probe check in the sandbox.

    :param root: The writable root holding probe.py.
    :param check: The probe check to run.
    :param args: The check's keyword arguments, written to args.json.
    :param ports: Host localhost ports passed as --port.
    :param options: Further command-line arguments, e.g. --ro and --rw directories.
    :param constants: Script constants the driver replaces before the launch.
    :param omit_globals: Wayland globals the driver removes from WAYLAND_GLOBALS.
    :param spawn: Let the launch reach start_guard; otherwise it fails there.
    :param pass_fds: Descriptors the driver inherits.
    :param terminal: Give the driver a terminal as its stdio.
    :return: The running driver.
    """
    (root / "args.json").write_text(json.dumps(args or {}))
    # A result left by an earlier run must not stand in for this one
    (root / "result.json").unlink(missing_ok=True)
    spec = {
        "root": str(root),
        "ports": list(ports),
        "options": list(options),
        "command": [HOST_PYTHON, "-I", str(root / "probe.py"), check],
        "constants": dict(constants or {}),
        "omit_globals": list(omit_globals),
        "spawn": spawn,
        "terminal": terminal,
    }
    return subprocess.Popen(
        [HOST_PYTHON, "-I", "-B", "-c", DRIVER, str(SCRIPT), json.dumps(spec)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        pass_fds=pass_fds,
    )


def finish(process: subprocess.Popen[str]) -> dict[str, Any]:
    """
    Wait for a driver and parse its outcome.

    A driver killed on timeout is the supervisor, so its guard stops the sandbox.

    :param process: The driver from start.
    :return: The outcome: status or error, and whether the launch reached start_guard.
    """
    try:
        stdout, stderr = process.communicate(timeout=LAUNCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        pytest.fail(f"the driver timed out; stderr:\n{stderr}\ncode.log:\n{log_tail()}")
    assert process.returncode == 0, f"the driver failed; stderr:\n{stderr}"
    return json.loads(stdout)


def result(root: Path, outcome: Mapping[str, Any]) -> Any:
    """
    Read the probe's result once the sandbox ran it to completion.

    :param root: The root the probe wrote result.json to.
    :param outcome: The driver's outcome.
    :return: The check's return value.
    """
    assert outcome.get("status") == 0, f"{outcome}; code.log:\n{log_tail()}"
    written = json.loads((root / "result.json").read_text())
    assert "exception" not in written, written.get("exception")
    return written["value"]


def probe(
    root: Path, check: str, args: Mapping[str, Any] | None = None, **kwargs
) -> Any:
    """
    Run one probe check in the sandbox and return its result.

    :param root: The writable root holding probe.py.
    :param check: The probe check to run.
    :param args: The check's keyword arguments.
    :param kwargs: Launch options, as for start.
    :return: The check's return value.
    """
    return result(root, finish(start(root, check, args, **kwargs)))


@contextmanager
def host_listener(address: str) -> Iterator[tuple[int, list[str]]]:
    """
    Listen on a host loopback address and send TOKEN to every connection.

    :param address: The address to listen on, 127.0.0.1 or ::1.
    :return: A context manager yielding the port and the peers accepted so far.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    accepted: list[str] = []
    stopped = threading.Event()
    with socket.socket(family, socket.SOCK_STREAM) as server:
        server.bind((address, 0))
        server.listen()
        server.settimeout(0.2)

        def serve() -> None:
            while not stopped.is_set():
                try:
                    connection, peer = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    accepted.append(peer[0])
                    connection.sendall(TOKEN.encode())

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield server.getsockname()[1], accepted
        finally:
            stopped.set()
            thread.join()


def host_receive(address: str, port: int) -> str:
    """
    Connect from the host and read what the peer sends.

    :param address: The loopback address.
    :param port: The port.
    :return: The text received, or the error's type name.
    """
    try:
        with socket.create_connection((address, port), timeout=2) as sock:
            return sock.recv(64).decode(errors="replace")
    except OSError as error:
        return type(error).__name__


def require_on_host(path: str) -> None:
    """
    Skip a probe whose target is missing on the host, where its absence proves nothing.

    :param path: The host path the probe targets.
    """
    if not os.path.lexists(path):
        pytest.skip(f"{path} does not exist on the host")


def host_ipv6_default_route() -> bool:
    """
    Tell whether the host has an IPv6 default route via a gateway, which pasta copies.

    :return: Whether such a route exists.
    """
    routes = Path("/proc/net/ipv6_route")
    if not routes.exists():
        return False
    return any(
        fields[0] == "0" * 32 and fields[1] == "00" and fields[4] != "0" * 32
        for fields in map(str.split, routes.read_text().splitlines())
    )


# The AC2 view, written from design.md's access table and plan.md's Key Decisions
# rather than read from the script, so an extra or missing bind fails the enumeration.
# The read-only system view and Flatpak's /sys subset
EXPECTED_SYSTEM_BINDS = (
    "/usr",
    "/etc",
    "/sys/block",
    "/sys/bus",
    "/sys/class",
    "/sys/dev",
    "/sys/devices",
)
# Read-only home binds, each mounted only when present on the host
EXPECTED_HOME_RO_BINDS = (
    ".micromamba",
    "bin",
    ".local/bin",
    ".config/nvim",
    ".local/share/uv/python",
    ".gitconfig",
    ".local/share/jupyter/kernels",
    ".local/share/fonts",
    ".fonts",
    ".config/fontconfig",
    ".icons",
    ".local/share/icons",
    ".themes",
    ".config/gtk-3.0",
    ".config/gtk-4.0",
)
# The reused profile, created on the host when missing, so always mounted
EXPECTED_HOME_RW_BINDS = (".config/Code", ".vscode", ".vscode-shared")
EXPECTED_STORE = HOME / ".local/share/vscode-sandbox"
# Host nodes bwrap's --dev binds into its /dev tmpfs (bubblewrap.c SETUP_MOUNT_DEV)
BWRAP_DEV_NODES = ("null", "zero", "full", "random", "urandom", "tty")


def unescape(field: str) -> str:
    """
    Decode a mountinfo path field, which writes whitespace and backslash as octal.

    :param field: The escaped field.
    :return: The path.
    """
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), field)


def host_submounts(source: str, target: str) -> list[str]:
    """
    List the host mounts below a bind source, placed below its target.

    bwrap binds recursively, so these come along with the source.

    :param source: The host path bound.
    :param target: Where the sandbox sees it.
    :return: The submounts' mount points in the sandbox.
    """
    base = Path(os.path.realpath(source))
    points = (
        Path(unescape(line.split()[4]))
        for line in Path("/proc/self/mountinfo").read_text().splitlines()
    )
    return [
        str(target / point.relative_to(base))
        for point in points
        if point != base and point.is_relative_to(base)
    ]


def expected_mounts(root: Path, option_dirs: Sequence[Path] = ()) -> list[str]:
    """
    Build the mount points the sandbox must have, one entry per mount.

    :param root: The test's read-write root.
    :param option_dirs: The directories passed as --ro or --rw.
    :return: The mount points, sorted, repeated where mounts stack.
    """
    binds = [
        *((path, path) for path in EXPECTED_SYSTEM_BINDS),
        # The driver's only path argument; a ROOTS entry in the script would be an extra
        # mount here, because the driver does not pass --only-args
        (str(root), str(root)),
        *((str(path), str(path)) for path in option_dirs),
        *(
            (str(HOME / relative), str(HOME / relative))
            for relative in EXPECTED_HOME_RO_BINDS
            if (HOME / relative).exists()
        ),
        *(
            (str(HOME / relative), str(HOME / relative))
            for relative in EXPECTED_HOME_RW_BINDS
        ),
        # The private store's caches; the store itself and code.log stay unmounted
        (str(EXPECTED_STORE / "cache"), str(HOME / ".cache")),
        (
            str(EXPECTED_STORE / "jupyter-runtime"),
            str(HOME / ".local/share/jupyter/runtime"),
        ),
    ]
    expected = [
        # bwrap's new root, a tmpfs. Its proc for the sandbox's PID namespace: bwrap
        # covers /proc/sys, sysrq-trigger, irq and bus only when they are writable, and
        # they are owned by the initial namespace's root, unmapped in bwrap's namespace
        "/",
        "/proc",
        # --dev: a tmpfs, host nodes bound in and a private devpts. No /dev/console,
        # which bwrap adds only when its stdout is a terminal; it is code.log
        "/dev",
        *(f"/dev/{node}" for node in BWRAP_DEV_NODES),
        "/dev/pts",
        # Fresh tmpfs mounts
        "/dev/shm",
        "/tmp",
        "/run",
        str(HOME),
        # GPU render nodes only
        *(str(node) for node in Path("/dev/dri").glob("renderD*")),
        # The security-context socket, and the sandbox resolv.conf where the host's
        # /etc/resolv.conf resolves to; their parents under /run are directories
        f"/run/user/{os.getuid()}/wayland-0",
        os.path.realpath("/etc/resolv.conf"),
        # The in-sandbox `code`, bound over the ~/bin shim when the host has one
        *([str(HOME / "bin/code")] if (HOME / "bin/code").exists() else []),
    ]
    for source, target in binds:
        expected += (target, *host_submounts(source, target))
    return sorted(expected)


def mount_difference(
    found: Sequence[str], expected: Sequence[str]
) -> dict[str, list[str]]:
    """
    Compare mount points as multisets, so a duplicated mount also counts.

    :param found: The sandbox's mount points.
    :param expected: The expected mount points.
    :return: The extra and the missing mount points, each sorted.
    """
    found_count, expected_count = Counter(found), Counter(expected)
    return {
        "extra": sorted((found_count - expected_count).elements()),
        "missing": sorted((expected_count - found_count).elements()),
    }


def wait_for_json(path: Path, process: subprocess.Popen[str]) -> dict[str, Any]:
    """
    Wait for the probe to publish a JSON file while the driver runs.

    :param path: The file the probe writes atomically.
    :param process: The driver.
    :return: The file's content.
    """
    deadline = time.monotonic() + 30
    while not path.exists():
        assert process.poll() is None, "the driver exited before the probe listened"
        assert time.monotonic() < deadline, f"no {path.name}; code.log:\n{log_tail()}"
        time.sleep(0.05)
    return json.loads(path.read_text())


@pytest.fixture
def root() -> Iterator[Path]:
    """Provide a writable root under $HOME holding the probe program."""
    path = Path(tempfile.mkdtemp(dir=Path.home(), prefix="vscode-sandbox-probe-"))
    path = path.resolve()
    (path / "probe.py").write_text(PROBE)
    yield path
    shutil.rmtree(path)


@pytest.fixture
def sibling() -> Iterator[Path]:
    """Provide a directory under $HOME next to the root, but outside it."""
    path = Path(tempfile.mkdtemp(dir=Path.home(), prefix="vscode-sandbox-sibling-"))
    yield path.resolve()
    shutil.rmtree(path)


@pytest.fixture
def option_dirs() -> Iterator[tuple[Path, Path]]:
    """Provide a --ro and a --rw directory under $HOME, outside the root."""
    paths = tuple(
        Path(tempfile.mkdtemp(dir=Path.home(), prefix=f"vscode-sandbox-{mode}-"))
        for mode in ("ro", "rw")
    )
    yield paths[0].resolve(), paths[1].resolve()
    for path in paths:
        shutil.rmtree(path)


# AC2: filesystem view


@pytest.mark.parametrize(
    "path",
    [
        str(HOME / ".ssh"),
        str(HOME / ".config/gh"),
        str(HOME / ".local/share/keyrings"),
        "/data",
    ],
)
def test_ac2_private_path_absent(root, path):
    require_on_host(path)

    assert probe(root, "exists", {"path": path}) is False


def test_ac2_sibling_outside_roots_absent(root, sibling):
    assert probe(root, "exists", {"path": str(sibling)}) is False


@pytest.mark.parametrize(
    "path",
    [
        "/usr",
        "/etc",
        *(
            str(HOME / relative)
            for relative in sandbox.HOME_RO_PATHS
            if (HOME / relative).exists()
        ),
    ],
)
def test_ac2_read_only_path_rejects_writes(root, path):
    assert probe(root, "write", {"path": path}) == "EROFS"


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        (None, None),
        (".config/Code", ".config/Code"),
        (".vscode-shared", ".vscode-shared"),
        (".cache", f"{sandbox.STORE}/cache"),
    ],
    ids=["root", ".config/Code", ".vscode-shared", ".cache"],
)
def test_ac2_root_profile_and_cache_writable(root, relative, source):
    name = f"vscode-sandbox-probe-{uuid.uuid4().hex}"
    path = (root if relative is None else HOME / relative) / name
    host_file = (root if source is None else HOME / source) / name
    try:
        created = probe(root, "create", {"path": str(path), "content": name})
        content = host_file.read_text() if host_file.exists() else None
    finally:
        host_file.unlink(missing_ok=True)

    assert created == "ok"
    assert content == name


def test_ac2_mounts_match_access_table(root):
    expected = expected_mounts(root)

    found = [unescape(field) for field in probe(root, "mounts")]

    assert mount_difference(found, expected) == {"extra": [], "missing": []}


def test_ac2_ro_dir_rejects_writes(root, option_dirs):
    ro, rw = option_dirs

    written = probe(
        root, "write", {"path": str(ro)}, options=("--ro", str(ro), "--rw", str(rw))
    )

    assert written == "EROFS"


def test_ac2_rw_dir_writable(root, option_dirs):
    ro, rw = option_dirs
    name = f"vscode-sandbox-probe-{uuid.uuid4().hex}"

    created = probe(
        root,
        "create",
        {"path": str(rw / name), "content": name},
        options=("--ro", str(ro), "--rw", str(rw)),
    )

    assert created == "ok"
    assert (rw / name).read_text() == name


def test_ac2_ro_dir_inside_root_rejects_writes_while_root_stays_writable(root):
    sub = root / "sub"
    sub.mkdir()
    name = f"vscode-sandbox-probe-{uuid.uuid4().hex}"
    options = ("--ro", str(sub))

    written = probe(root, "write", {"path": str(sub)}, options=options)
    created = probe(
        root, "create", {"path": str(root / name), "content": name}, options=options
    )

    assert written == "EROFS"
    assert created == "ok"
    assert (root / name).read_text() == name


def test_ac2_mounts_match_access_table_with_option_dirs(root, option_dirs):
    ro, rw = option_dirs
    expected = expected_mounts(root, option_dirs)

    mounts = probe(root, "mounts", options=("--ro", str(ro), "--rw", str(rw)))
    found = [unescape(field) for field in mounts]

    assert mount_difference(found, expected) == {"extra": [], "missing": []}


# AC3: no route to host code execution


@pytest.mark.parametrize(
    "path",
    [
        f"/run/user/{os.getuid()}/bus",
        "/run/dbus/system_bus_socket",
        f"/run/user/{os.getuid()}/podman",
        "/tmp/.X11-unix",
    ],
)
def test_ac3_bus_podman_and_x11_sockets_absent(root, path):
    require_on_host(path)

    assert probe(root, "exists", {"path": path}) is False


@pytest.mark.parametrize("name", ["DBUS_SESSION_BUS_ADDRESS", "DISPLAY"])
def test_ac3_bus_and_x11_variables_unset(root, name, monkeypatch):
    # The driver inherits it, whether or not this session has it
    monkeypatch.setenv(name, "vscode-sandbox-probe")

    assert probe(root, "environment", {"name": name}) is False


def test_ac3_dri_holds_only_render_nodes(root):
    render_nodes = sorted(path.name for path in Path("/dev/dri").glob("renderD*"))

    assert probe(root, "dri") == render_nodes


def test_ac3_wayland_globals_allowlisted(root):
    names = probe(root, "wayland")

    assert names
    assert set(names) <= sandbox.WAYLAND_GLOBALS


def test_ac3_tiocsti_on_stdin_denied(root):
    assert probe(root, "stdin_tiocsti") == "EPERM"


def test_ac3_host_processes_invisible(root):
    token = f"vscode-sandbox-sentinel-{uuid.uuid4().hex}"
    sentinel = subprocess.Popen([token, "600"], executable="/usr/bin/sleep")
    try:
        # cmdline reads empty until exec has set up the new argument area
        deadline = time.monotonic() + 5
        cmdline = Path(f"/proc/{sentinel.pid}/cmdline")
        while token.encode() not in cmdline.read_bytes():
            assert time.monotonic() < deadline, "the sentinel's token never showed"
            time.sleep(0.01)
        found = probe(root, "processes", {"token": token})
        assert sentinel.poll() is None
    finally:
        sentinel.kill()
        sentinel.wait()

    assert found["matches"] == []
    # bwrap's init and the probe itself, so /proc was readable
    assert found["scanned"] >= 2


@pytest.mark.parametrize("flag", ["CLONE_NEWUSER", "CLONE_NEWNS"])
def test_ac3_unshare_fails(root, flag):
    assert probe(root, "unshare", {"flag": flag}) != "ok"


def test_ac3_seccomp_filter_active(root):
    assert probe(root, "seccomp") == "2"


# Each errno differs from what the kernel alone returns inside bwrap
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("clone_newuser", "EPERM"),
        ("clone3", "ENOSYS"),
        ("fsopen", "ENOSYS"),
        ("ptrace_traceme", "EPERM"),
        ("add_key", "EPERM"),
        ("personality", "EPERM"),
        ("ioctl_tiocsti_high", "EPERM"),
        ("ioctl_tiocsti", "EPERM"),
        ("socket_packet", "EAFNOSUPPORT"),
    ],
)
def test_ac3_seccomp_denies_syscall(root, name, expected):
    assert probe(root, "syscall", {"name": name}) == expected


def test_ac3_only_stdio_descriptors_inherited(root):
    # The probe's own descriptors: what it holds when started on the host with stdio
    (root / "args.json").write_text("{}")
    subprocess.run(
        [HOST_PYTHON, "-I", str(root / "probe.py"), "fds"],
        stdin=subprocess.DEVNULL,
        check=True,
    )
    own_fds = json.loads((root / "result.json").read_text())["value"]
    read_end, write_end = os.pipe()
    directory = os.open(root, os.O_RDONLY)
    sentinels = (read_end, write_end, directory)
    for fd in sentinels:
        os.set_inheritable(fd, True)
    try:
        open_fds = probe(root, "fds", pass_fds=sentinels)
    finally:
        for fd in sentinels:
            os.close(fd)

    assert own_fds[:3] == ["0", "1", "2"]
    assert open_fds == own_fds


def test_ac3_stdio_not_terminals(root):
    assert probe(root, "ttys", terminal=True) == [False, False, False]


# AC4: network


def test_ac4_dns_and_https_reach_the_internet(root):
    found = probe(root, "internet", {"host": "fedoraproject.org", "port": 443})

    assert found["addresses"]
    assert found["connected"] in found["addresses"], found["errors"]


def test_ac4_host_loopback_unreachable(root):
    with (
        host_listener("127.0.0.1") as (port_4, accepted_4),
        host_listener("::1") as (port_6, accepted_6),
    ):
        targets = {
            "127.0.0.1": ["127.0.0.1", port_4],
            "::1": ["::1", port_6],
            "IPv4 gateway": ["@gateway4", port_4],
            "IPv6 gateway": ["@gateway6", port_6],
        }
        reached = probe(root, "connect", {"targets": targets})

    assert accepted_4 == []
    assert accepted_6 == []
    assert all(outcome["received"] != TOKEN for outcome in reached.values()), reached
    assert reached["IPv4 gateway"]["address"] is not None
    if host_ipv6_default_route():
        assert reached["IPv6 gateway"]["address"] is not None, reached


def test_ac4_listed_port_reachable(root):
    with host_listener("127.0.0.1") as (port, accepted):
        targets = {"forwarded": ["127.0.0.1", port]}
        reached = probe(root, "connect", {"targets": targets}, ports=(port,))

    assert reached["forwarded"]["received"] == TOKEN, reached
    assert accepted == ["127.0.0.1"]


def test_ac4_sandbox_listener_unreachable_from_host(root):
    process = start(root, "inbound", {"token": TOKEN})
    attempts = []
    try:
        port = wait_for_json(root / "listening.json", process)["port"]
        # pasta's automatic forwarding binds a host port only at its next scan of the
        # sandbox's listeners, so keep trying for longer than that
        deadline = time.monotonic() + INBOUND_WINDOW
        while time.monotonic() < deadline:
            attempts += (
                host_receive(address, port) for address in ("127.0.0.1", "::1")
            )
            time.sleep(0.1)
    finally:
        # Ends the probe, so the driver is gone before the next launch takes the lock
        (root / "done").touch()
        outcome = finish(process)
    found = result(root, outcome)

    assert TOKEN not in attempts, sorted(set(attempts))
    assert found["done"] is True
    assert found["accepted"] == [], sorted(set(attempts))


def test_ac4_host_abstract_socket_refused(root):
    name = f"vscode-sandbox-probe-{uuid.uuid4().hex}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(f"\0{name}")
        server.listen()
        refused = probe(root, "abstract", {"name": name})

    assert refused == "ECONNREFUSED"


# AC6: missing protections abort before anything is spawned


def test_ac6_missing_pasta_fails_before_spawning(root):
    missing = root / "missing-pasta"

    outcome = finish(
        start(root, "seccomp", constants={"PASTA": str(missing)}, spawn=False)
    )

    assert outcome == {
        "error": f"{missing} is missing or not executable",
        "spawned": False,
    }


def test_ac6_unlisted_wayland_global_aborts_before_spawning(root):
    outcome = finish(start(root, "seccomp", omit_globals=("wl_seat",), spawn=False))

    assert outcome == {
        "error": "the Wayland listener advertises globals outside WAYLAND_GLOBALS: "
        "wl_seat",
        "spawned": False,
    }


# AC7: the sandbox cannot modify the launch path or toolchains


@pytest.mark.parametrize(
    "relative",
    [
        "bin/vscode-sandbox",
        "bin/code",
        ".micromamba",
        ".local/share/jupyter/kernels",
    ],
)
def test_ac7_launcher_and_toolchain_not_writable(root, relative):
    path = HOME / relative
    require_on_host(str(path))

    assert probe(root, "write", {"path": str(path)}) == "EROFS"


def test_ac7_host_applications_dir_absent(root):
    path = HOME / ".local/share/applications"
    require_on_host(str(path))

    assert probe(root, "exists", {"path": str(path)}) is False
