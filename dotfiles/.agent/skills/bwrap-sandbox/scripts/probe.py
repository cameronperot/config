#!/usr/bin/env python3
"""Probe isolation properties from inside a bwrap sandbox.

Run inside the sandbox under test, typically fed on stdin through the
launcher's --exec slot:

    launcher --exec -- /usr/bin/python3 -I - CHECK... < probe.py

Each CHECK is NAME or NAME:ARG. One JSON object per check is printed to
stdout. The exit status is 0 only when every result is "pass" or
"not-applicable", 1 when any check fails or errors, and 2 on a usage error.
Standard library only; Linux on x86_64 or aarch64 for the raw-syscall checks.
"""

import ctypes
import errno
import json
import os
import platform
import socket
import sys
import termios
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

PASS = "pass"
FAIL = "fail"
ERROR = "error"
NOT_APPLICABLE = "not-applicable"
SUCCESS_RESULTS = frozenset({PASS, NOT_APPLICABLE})

# An address the kernel rejects with EFAULT, as in bubblewrap's tests/try-syscall.c
WRONG_POINTER = 1
CONNECT_TIMEOUT = 3.0
# Errors that show the path is closed, as opposed to a local resource failure
BLOCKED_ERRNOS = frozenset(
    {
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EADDRNOTAVAIL,
        errno.EPERM,
        errno.EACCES,
        errno.EAFNOSUPPORT,
    }
)
# High bits the kernel ignores in an ioctl request; a seccomp rule that compares all
# 64 bits misses them (CVE-2019-10063)
IOCTL_HIGH_BITS = 0x123 << 32
# clone3's struct clone_args size as of Linux 5.5
CLONE_ARGS_SIZE = 88
PTRACE_PEEKDATA = 2
PERSONALITY_QUERY = 0xFFFFFFFF
IO_URING_DISABLED = "/proc/sys/kernel/io_uring_disabled"

SYSCALL_NUMBERS = {
    "x86_64": {
        "ioctl": 16,
        "ptrace": 101,
        "personality": 135,
        "chroot": 161,
        "add_key": 248,
        "perf_event_open": 298,
        "setns": 308,
        "io_uring_setup": 425,
        "clone3": 435,
    },
    "aarch64": {
        "ioctl": 29,
        "ptrace": 117,
        "personality": 92,
        "chroot": 51,
        "add_key": 217,
        "perf_event_open": 241,
        "setns": 268,
        "io_uring_setup": 425,
        "clone3": 435,
    },
}

# Arguments that fail harmlessly with the given errno when no filter intervenes;
# None means the unfiltered call succeeds without side effects
SYSCALL_PROBES: dict[str, tuple[tuple[int, ...], int | None]] = {
    "ptrace": ((PTRACE_PEEKDATA, -1, 0, 0), errno.ESRCH),
    "chroot": ((WRONG_POINTER,), errno.EFAULT),
    "add_key": ((WRONG_POINTER, 0, 0, 0, 0), errno.EFAULT),
    "perf_event_open": ((WRONG_POINTER, 0, -1, -1, 0), errno.EFAULT),
    "setns": ((-1, 0), errno.EBADF),
    "personality": ((PERSONALITY_QUERY,), None),
    "io_uring_setup": ((1, WRONG_POINTER), errno.EFAULT),
    "clone3": ((WRONG_POINTER, CLONE_ARGS_SIZE), errno.EFAULT),
}

USAGE = """\
usage: probe.py CHECK...

Checks (NAME or NAME:ARG):
  hidden:PATH               PATH does not exist (ENOENT)
  readonly:PATH             creating a file in directory PATH, or writing file
                            PATH, fails with EROFS
  writable:PATH             creating and removing a file in directory PATH works
  pid-hidden:TOKEN          no visible process has argv[0] equal to TOKEN
  userns-blocked            creating a user namespace fails
  connect-blocked:HOST:PORT TCP connection fails (use IP literals; [::1]:PORT)
  connect-allowed:HOST:PORT TCP connection succeeds
  fds-only:N,N,...          only the listed file descriptors are open
  pgrp-isolated             process group and session leaders are inside the
                            sandbox's PID namespace
  seccomp-active            a seccomp filter is loaded (Seccomp: 2)
  tty-ioctl-blocked         TIOCSTI, TIOCLINUX and high-bit TIOCSTI fail with
                            EPERM rather than EBADF
  syscall-denied:NAME[:ERRNO]
                            NAME fails with ERRNO (default EPERM); NAME is one
                            of: {syscalls}
"""


@dataclass(frozen=True)
class Result:
    """Outcome of one check."""

    check: str
    arg: str
    result: str
    expected: str
    observed: str


class UsageError(Exception):
    """A malformed check specification."""


def errno_name(code: int) -> str:
    """Return the symbolic name of an errno value.

    Args:
        code: The errno value.

    Returns:
        The name, such as "EPERM", or the number when it has no name.
    """
    return errno.errorcode.get(code, str(code))


def check_hidden(arg: str) -> Result:
    """Check that a path does not exist inside the sandbox.

    Args:
        arg: The path.

    Returns:
        The check result.
    """
    try:
        os.stat(arg)
    except FileNotFoundError:
        return Result("hidden", arg, PASS, "ENOENT", "ENOENT")
    except OSError as exc:
        return Result("hidden", arg, ERROR, "ENOENT", errno_name(exc.errno))
    return Result("hidden", arg, FAIL, "ENOENT", "exists")


def check_readonly(arg: str) -> Result:
    """Check that writing to a path fails because its mount is read-only.

    Args:
        arg: A directory, in which a file creation is attempted, or a file,
            which is opened for appending.

    Returns:
        The check result; EACCES and other errors are inconclusive.
    """
    is_dir = os.path.isdir(arg)
    target = os.path.join(arg, f".probe-{os.getpid()}") if is_dir else arg
    flags = os.O_WRONLY | (os.O_CREAT | os.O_EXCL if is_dir else os.O_APPEND)
    try:
        fd = os.open(target, flags, 0o600)
    except OSError as exc:
        result = PASS if exc.errno == errno.EROFS else ERROR
        return Result("readonly", arg, result, "EROFS", errno_name(exc.errno))
    os.close(fd)
    if is_dir:
        os.unlink(target)
    return Result("readonly", arg, FAIL, "EROFS", "writable")


def check_writable(arg: str) -> Result:
    """Check that a file can be created and removed in a directory.

    Args:
        arg: The directory.

    Returns:
        The check result.
    """
    target = os.path.join(arg, f".probe-{os.getpid()}")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        os.unlink(target)
    except OSError as exc:
        return Result("writable", arg, FAIL, "writable", errno_name(exc.errno))
    return Result("writable", arg, PASS, "writable", "writable")


def check_pid_hidden(arg: str) -> Result:
    """Check that no visible process has the token as its argv[0].

    An exact argv[0] match keeps bwrap's own PID 1, whose command line contains
    "pid-hidden:TOKEN", from counting as the host sentinel.

    Args:
        arg: The argv[0] of the host sentinel process (bash's exec -a TOKEN).

    Returns:
        The check result; an unreadable /proc is inconclusive.
    """
    try:
        with open("/proc/self/cmdline", "rb") as file:
            file.read()
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError as exc:
        return Result(
            "pid-hidden", arg, ERROR, "absent", f"/proc: {errno_name(exc.errno)}"
        )
    token = arg.encode()
    own = {str(os.getpid())}
    for pid in pids:
        if pid in own:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as file:
                cmdline = file.read()
        except OSError:
            continue
        if cmdline.split(b"\0", 1)[0] == token:
            return Result("pid-hidden", arg, FAIL, "absent", f"pid {pid}")
    return Result("pid-hidden", arg, PASS, "absent", f"{len(pids)} processes scanned")


def check_userns_blocked(arg: str) -> Result:
    """Check that creating a user namespace fails, in a disposable child.

    Args:
        arg: Unused.

    Returns:
        The check result.
    """
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            os.unshare(os.CLONE_NEWUSER)
            code = 0
        except OSError as exc:
            code = exc.errno
        os.write(write_fd, str(code).encode())
        os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd) as file:
        code = int(file.read() or -1)
    os.waitpid(pid, 0)
    if code == 0:
        return Result("userns-blocked", arg, FAIL, "failure", "created")
    if code < 0:
        return Result("userns-blocked", arg, ERROR, "failure", "child reported nothing")
    return Result("userns-blocked", arg, PASS, "failure", errno_name(code))


def parse_address(arg: str) -> tuple[str, int]:
    """Split HOST:PORT or [V6]:PORT.

    Args:
        arg: The address specification.

    Returns:
        The host and port.

    Raises:
        UsageError: When the specification is malformed.
    """
    host, sep, port = arg.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise UsageError(f"expected HOST:PORT with PORT 1-65535, got {arg!r}")
    return host.strip("[]"), int(port)


def parse_fds(arg: str) -> frozenset[int]:
    """Parse a comma-separated descriptor list.

    Args:
        arg: The list, such as "0,1,2".

    Returns:
        The descriptor numbers.

    Raises:
        UsageError: When an item is not a non-negative integer.
    """
    items = [item for item in arg.split(",") if item]
    if not items or not all(item.isdigit() for item in items):
        raise UsageError(f"expected N,N,..., got {arg!r}")
    return frozenset(int(item) for item in items)


def parse_syscall(arg: str) -> tuple[str, int]:
    """Parse NAME or NAME:ERRNO for syscall-denied.

    Args:
        arg: The specification.

    Returns:
        The syscall name and the expected errno value.

    Raises:
        UsageError: When the syscall or errno name is unknown.
    """
    name, _, wanted = arg.partition(":")
    if name not in SYSCALL_PROBES:
        raise UsageError(f"unsupported syscall {name!r}")
    expected = getattr(errno, wanted or "EPERM", None)
    if not isinstance(expected, int):
        raise UsageError(f"unknown errno {wanted!r}")
    if expected == SYSCALL_PROBES[name][1]:
        raise UsageError(
            f"{wanted} is what unfiltered {name} returns; it proves nothing"
        )
    return name, expected


def try_connect(arg: str) -> tuple[str, str]:
    """Attempt a TCP connection and classify the outcome.

    Args:
        arg: The HOST:PORT specification.

    Returns:
        ("connected", ...), ("blocked", reason) for refusals, unreachable routes,
        timeouts and policy denials, or ("inconclusive", reason) for name
        resolution and local resource failures.
    """
    host, port = parse_address(arg)
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return "connected", "connected"
    except TimeoutError:
        return "blocked", "timeout"
    except socket.gaierror as exc:
        return "inconclusive", f"resolution failed: {exc}"
    except OSError as exc:
        name = errno_name(exc.errno) if exc.errno is not None else str(exc)
        return ("blocked" if exc.errno in BLOCKED_ERRNOS else "inconclusive"), name


def check_connect_blocked(arg: str) -> Result:
    """Check that a TCP connection fails.

    Args:
        arg: The HOST:PORT specification; use IP literals.

    Returns:
        The check result; resolution and local resource failures are inconclusive.
    """
    outcome, observed = try_connect(arg)
    result = {"connected": FAIL, "blocked": PASS}.get(outcome, ERROR)
    return Result("connect-blocked", arg, result, "unreachable", observed)


def check_connect_allowed(arg: str) -> Result:
    """Check that a TCP connection succeeds.

    Args:
        arg: The HOST:PORT specification.

    Returns:
        The check result.
    """
    outcome, observed = try_connect(arg)
    result = {"connected": PASS, "blocked": FAIL}.get(outcome, ERROR)
    return Result("connect-allowed", arg, result, "connected", observed)


def open_fds() -> list[int]:
    """List the open file descriptors, excluding the one used to list them.

    Returns:
        The descriptor numbers, sorted.
    """
    listed = [int(name) for name in os.listdir("/proc/self/fd")]
    fds = []
    for fd in listed:
        try:
            os.fstat(fd)
        except OSError:
            continue
        fds.append(fd)
    return sorted(fds)


def check_fds_only(arg: str) -> Result:
    """Check that only the listed file descriptors are open.

    Args:
        arg: Comma-separated descriptor numbers, such as "0,1,2".

    Returns:
        The check result.

    Raises:
        UsageError: When the list is malformed.
    """
    allowed = parse_fds(arg)
    try:
        fds = open_fds()
    except OSError as exc:
        return Result(
            "fds-only", arg, ERROR, arg, f"/proc/self/fd: {errno_name(exc.errno)}"
        )
    extra = [fd for fd in fds if fd not in allowed]
    observed = ",".join(map(str, fds))
    return Result("fds-only", arg, FAIL if extra else PASS, arg, observed)


def check_pgrp_isolated(arg: str) -> Result:
    """Check that the process group and session leaders are inside the PID namespace.

    getpgrp() and getsid() report 0 when the leader lives outside the caller's PID
    namespace, which means outside processes share the group or session. Without a
    bwrap PID namespace the leaders are always visible, so the check cannot decide.

    Args:
        arg: Unused.

    Returns:
        The check result.
    """
    try:
        with open("/proc/1/comm") as file:
            init = file.read().strip()
    except OSError as exc:
        return Result(
            "pgrp-isolated",
            arg,
            ERROR,
            "leaders inside",
            f"/proc/1: {errno_name(exc.errno)}",
        )
    if init != "bwrap":
        return Result(
            "pgrp-isolated",
            arg,
            ERROR,
            "leaders inside",
            f"PID 1 is {init!r}, not bwrap",
        )
    pgrp, sid = os.getpgrp(), os.getsid(0)
    observed = f"pgrp={pgrp} sid={sid}"
    result = PASS if pgrp != 0 and sid != 0 else FAIL
    return Result("pgrp-isolated", arg, result, "leaders inside", observed)


def check_seccomp_active(arg: str) -> Result:
    """Check that a seccomp filter is loaded.

    Args:
        arg: Unused.

    Returns:
        The check result.
    """
    try:
        with open("/proc/self/status") as file:
            fields = dict(line.split(":", 1) for line in file if ":" in line)
    except OSError as exc:
        return Result(
            "seccomp-active", arg, ERROR, "2", f"/proc: {errno_name(exc.errno)}"
        )
    mode = fields.get("Seccomp", "").strip()
    if not mode:
        return Result("seccomp-active", arg, ERROR, "2", "no Seccomp field")
    return Result("seccomp-active", arg, PASS if mode == "2" else FAIL, "2", mode)


def raw_syscall(name: str, args: Sequence[int]) -> int:
    """Invoke a syscall by number for the running architecture.

    Args:
        name: The syscall name, a key of SYSCALL_NUMBERS' tables.
        args: The integer arguments.

    Returns:
        0 when the call succeeded, else the errno it failed with.

    Raises:
        KeyError: When the architecture has no syscall table.
    """
    number = SYSCALL_NUMBERS[platform.machine()][name]
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    ret = libc.syscall(ctypes.c_long(number), *(ctypes.c_long(arg) for arg in args))
    return ctypes.get_errno() if ret == -1 else 0


def check_tty_ioctl_blocked(arg: str) -> Result:
    """Check that terminal-injection ioctls are filtered, using an invalid descriptor.

    Unfiltered, each call fails with EBADF because fd -1 is invalid, so nothing is
    ever injected; a filter answers EPERM first.

    Args:
        arg: Unused.

    Returns:
        The check result.
    """
    requests = {
        "TIOCSTI": termios.TIOCSTI,
        "TIOCLINUX": termios.TIOCLINUX,
        "TIOCSTI|high-bits": termios.TIOCSTI | IOCTL_HIGH_BITS,
    }
    try:
        observed = {
            label: raw_syscall("ioctl", (-1, request, WRONG_POINTER))
            for label, request in requests.items()
        }
    except KeyError:
        return Result(
            "tty-ioctl-blocked",
            arg,
            ERROR,
            "EPERM",
            f"no table for {platform.machine()}",
        )
    summary = " ".join(
        f"{label}={errno_name(code)}" for label, code in observed.items()
    )
    codes = set(observed.values())
    if codes == {errno.EPERM}:
        result = PASS
    elif errno.EBADF in codes:
        result = FAIL
    else:
        result = ERROR
    return Result("tty-ioctl-blocked", arg, result, "EPERM", summary)


def io_uring_restricted() -> str | None:
    """Report whether a sysctl restricts io_uring, which also yields EPERM.

    Returns:
        The kernel.io_uring_disabled value when it is non-zero, else None.
    """
    try:
        with open(IO_URING_DISABLED) as file:
            value = file.read().strip()
    except OSError:
        return None
    return value if value not in ("", "0") else None


def check_syscall_denied(arg: str) -> Result:
    """Check that a syscall fails with the filter's errno rather than the kernel's.

    Args:
        arg: NAME or NAME:ERRNO, such as "ptrace" or "clone3:ENOSYS".

    Returns:
        The check result.

    Raises:
        UsageError: When the syscall or errno name is unknown.
    """
    name, expected = parse_syscall(arg)
    restricted = io_uring_restricted() if name == "io_uring_setup" else None
    if restricted is not None:
        # 2 disables io_uring for everyone; 1 still allows a configured group, so an
        # EPERM could come from the sysctl instead of the filter
        result = NOT_APPLICABLE if restricted == "2" else ERROR
        observed = f"io_uring_disabled={restricted}"
        return Result("syscall-denied", arg, result, errno_name(expected), observed)
    args, unfiltered = SYSCALL_PROBES[name]
    try:
        code = raw_syscall(name, args)
    except KeyError:
        return Result(
            "syscall-denied",
            arg,
            ERROR,
            errno_name(expected),
            f"no table for {platform.machine()}",
        )
    observed = "success" if code == 0 else errno_name(code)
    if code == expected:
        result = PASS
    elif code == 0 or code == unfiltered:
        result = FAIL
    else:
        result = ERROR
    return Result("syscall-denied", arg, result, errno_name(expected), observed)


CHECKS: dict[str, tuple[Callable[[str], Result], Callable[[str], object] | None]] = {
    "hidden": (check_hidden, str),
    "readonly": (check_readonly, str),
    "writable": (check_writable, str),
    "pid-hidden": (check_pid_hidden, str),
    "userns-blocked": (check_userns_blocked, None),
    "connect-blocked": (check_connect_blocked, parse_address),
    "connect-allowed": (check_connect_allowed, parse_address),
    "fds-only": (check_fds_only, parse_fds),
    "pgrp-isolated": (check_pgrp_isolated, None),
    "seccomp-active": (check_seccomp_active, None),
    "tty-ioctl-blocked": (check_tty_ioctl_blocked, None),
    "syscall-denied": (check_syscall_denied, parse_syscall),
}


def parse_check(spec: str) -> tuple[Callable[[str], Result], str]:
    """Resolve and validate a check specification before any check runs.

    Args:
        spec: NAME or NAME:ARG.

    Returns:
        The check function and its argument ("" when the check takes none).

    Raises:
        UsageError: When the name is unknown or the argument is missing, extra or
            malformed.
    """
    name, sep, arg = spec.partition(":")
    if name not in CHECKS:
        raise UsageError(f"unknown check {name!r}")
    func, validate = CHECKS[name]
    if validate is None:
        if sep:
            raise UsageError(f"{name} takes no argument")
        return func, arg
    if not arg:
        raise UsageError(f"{name} needs an argument")
    validate(arg)
    return func, arg


def main(argv: Sequence[str]) -> int:
    """Run the requested checks and print one JSON object per check.

    Args:
        argv: The check specifications.

    Returns:
        The exit status.
    """
    if not argv or argv[0] in ("-h", "--help"):
        stream = sys.stdout if argv else sys.stderr
        stream.write(USAGE.format(syscalls=", ".join(SYSCALL_PROBES)))
        return 0 if argv else 2
    try:
        parsed = [parse_check(spec) for spec in argv]
    except UsageError as exc:
        print(f"probe.py: error: {exc}", file=sys.stderr)
        return 2
    status = 0
    for func, arg in parsed:
        try:
            result = func(arg)
        except OSError as exc:
            name = func.__name__.removeprefix("check_").replace("_", "-")
            result = Result(name, arg, ERROR, "a decision", f"unexpected {exc!r}")
        print(json.dumps(asdict(result)), flush=True)
        if result.result not in SUCCESS_RESULTS:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
