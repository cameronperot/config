"""Tests for the bwrap-sandbox skill's in-sandbox probe script.

Kernel enforcement is only observable inside a real sandbox on a host, so these
tests cover the parts that decide what counts as verified: argument validation,
result classification and exit status.
"""

import errno
import importlib.util
import io
import json
import platform
import socket
import subprocess
import sys
import uuid
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

PROBE = (
    Path(__file__).resolve().parent.parent
    / "dotfiles/.agent/skills/bwrap-sandbox/scripts/probe.py"
)


@pytest.fixture(scope="module")
def probe():
    """Import the probe script as a module."""
    loader = SourceFileLoader("bwrap_probe", str(PROBE))
    spec = importlib.util.spec_from_loader("bwrap_probe", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # Keep the skill directory free of __pycache__
    dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module


def fake_open(contents: dict[str, str]):
    """Build an open() replacement serving fixed file contents."""

    def opener(path, *args, **kwargs):
        if path not in contents:
            raise FileNotFoundError(errno.ENOENT, "missing", path)
        return io.StringIO(contents[path])

    return opener


@pytest.mark.parametrize(
    "spec",
    [
        "nonsense",
        "hidden",
        "hidden:",
        "userns-blocked:extra",
        "connect-blocked:no-port",
        "connect-allowed:host:port",
        "fds-only:0,x",
        "fds-only:,",
        "syscall-denied:reboot",
        "syscall-denied:ptrace:ENOTANERRNO",
        "syscall-denied:ptrace:errorcode",
        "syscall-denied:ptrace:ESRCH",
        "syscall-denied:clone3:EFAULT",
        "connect-blocked:127.0.0.1:0",
        "connect-blocked:127.0.0.1:65536",
    ],
)
def test_parse_check_rejects_malformed_specs(probe, spec):
    # Act / Assert
    with pytest.raises(probe.UsageError):
        probe.parse_check(spec)


@pytest.mark.parametrize(
    ("spec", "arg"),
    [
        ("hidden:/home/u/.ssh", "/home/u/.ssh"),
        ("userns-blocked", ""),
        ("connect-blocked:[::1]:8765", "[::1]:8765"),
        ("fds-only:0,1,2", "0,1,2"),
        ("syscall-denied:clone3:ENOSYS", "clone3:ENOSYS"),
    ],
)
def test_parse_check_accepts_valid_specs(probe, spec, arg):
    # Act
    _, parsed_arg = probe.parse_check(spec)

    # Assert
    assert parsed_arg == arg


def test_parse_address_handles_ipv6(probe):
    # Act / Assert
    assert probe.parse_address("[::1]:8765") == ("::1", 8765)


def test_main_validates_every_spec_before_running_any(probe, capsys):
    # Act
    status = probe.main(["hidden:/nonexistent-probe-path", "connect-blocked:bad"])

    # Assert
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "expected HOST:PORT" in captured.err


def test_main_without_checks_is_a_usage_error(probe, capsys):
    # Act
    status = probe.main([])

    # Assert
    assert status == 2
    assert "usage:" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("results", "status"),
    [
        (("pass", "not-applicable"), 0),
        (("pass", "fail"), 1),
        (("pass", "error"), 1),
    ],
)
def test_main_exit_status_counts_only_pass_and_not_applicable(
    probe, monkeypatch, capsys, results, status
):
    # Arrange
    outcomes = iter(results)

    def fake(arg):
        return probe.Result("fake", arg, next(outcomes), "x", "y")

    monkeypatch.setitem(probe.CHECKS, "fake", (fake, None))

    # Act
    exit_status = probe.main(["fake", "fake"])

    # Assert
    lines = capsys.readouterr().out.splitlines()
    assert exit_status == status
    assert [json.loads(line)["result"] for line in lines] == list(results)


def test_hidden_passes_only_on_enoent(probe, tmp_path):
    # Arrange
    existing = tmp_path / "sentinel"
    existing.write_text("x")

    # Act / Assert
    assert probe.check_hidden(str(tmp_path / "absent")).result == "pass"
    assert probe.check_hidden(str(existing)).result == "fail"


def test_hidden_permission_error_is_inconclusive(probe, monkeypatch):
    # Arrange
    def denied(path):
        raise PermissionError(errno.EACCES, "denied", path)

    monkeypatch.setattr(probe.os, "stat", denied)

    # Act
    result = probe.check_hidden("/somewhere")

    # Assert
    assert result.result == "error"
    assert result.observed == "EACCES"


def test_readonly_fails_and_cleans_up_on_a_writable_directory(probe, tmp_path):
    # Act
    result = probe.check_readonly(str(tmp_path))

    # Assert
    assert result.result == "fail"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("code", "expected"), [(errno.EROFS, "pass"), (errno.EACCES, "error")]
)
def test_readonly_requires_erofs(probe, monkeypatch, tmp_path, code, expected):
    # Arrange
    def refuse(path, flags, mode=0o777):
        raise OSError(code, "refused", path)

    monkeypatch.setattr(probe.os, "open", refuse)

    # Act
    result = probe.check_readonly(str(tmp_path))

    # Assert
    assert result.result == expected


def test_writable_passes_on_a_writable_directory(probe, tmp_path):
    # Act / Assert
    assert probe.check_writable(str(tmp_path)).result == "pass"
    assert list(tmp_path.iterdir()) == []


def test_pid_hidden_matches_the_sentinel_argv0_exactly(probe):
    # Arrange: argv[0] is the token, as bash's exec -a sets it on the host
    token = f"bwrap-probe-sentinel-{uuid.uuid4().hex}"
    sentinel = subprocess.Popen([token, "30"], executable="/bin/sleep")

    # Act
    try:
        result = probe.check_pid_hidden(token)
    finally:
        sentinel.kill()
        sentinel.wait()

    # Assert
    assert result.result == "fail"


def test_pid_hidden_ignores_the_token_in_later_arguments(probe):
    # Arrange: bwrap's PID 1 carries "pid-hidden:TOKEN" among its arguments
    token = f"bwrap-probe-sentinel-{uuid.uuid4().hex}"
    lookalike = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", f"pid-hidden:{token}"]
    )

    # Act
    try:
        result = probe.check_pid_hidden(token)
    finally:
        lookalike.kill()
        lookalike.wait()

    # Assert
    assert result.result == "pass"


def test_userns_blocked_passes_when_unshare_fails(probe, monkeypatch):
    # Arrange
    def refuse(flags):
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(probe.os, "unshare", refuse)

    # Act
    result = probe.check_userns_blocked("")

    # Assert
    assert result.result == "pass"
    assert result.observed == "ENOSPC"


def test_userns_blocked_fails_when_unshare_succeeds(probe, monkeypatch):
    # Arrange
    monkeypatch.setattr(probe.os, "unshare", lambda flags: None)

    # Act / Assert
    assert probe.check_userns_blocked("").result == "fail"


def test_connect_checks_against_a_live_listener(probe):
    # Arrange
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]

        # Act
        allowed = probe.check_connect_allowed(f"127.0.0.1:{port}")
        blocked = probe.check_connect_blocked(f"127.0.0.1:{port}")

    # Assert
    assert allowed.result == "pass"
    assert blocked.result == "fail"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (errno.ECONNREFUSED, "pass"),
        (errno.ENETUNREACH, "pass"),
        (errno.EMFILE, "error"),
    ],
)
def test_connect_blocked_classifies_errors(probe, monkeypatch, code, expected):
    # Arrange
    def refuse(address, timeout):
        raise OSError(code, "refused")

    monkeypatch.setattr(probe.socket, "create_connection", refuse)

    # Act / Assert
    assert probe.check_connect_blocked("127.0.0.1:80").result == expected


def test_connect_blocked_treats_resolution_failure_as_inconclusive(probe):
    # Act
    result = probe.check_connect_blocked("no-such-host.invalid:80")

    # Assert
    assert result.result == "error"


def test_fds_only_flags_extra_descriptors(probe, monkeypatch):
    # Arrange
    monkeypatch.setattr(probe, "open_fds", lambda: [0, 1, 2, 7])

    # Act
    result = probe.check_fds_only("0,1,2")

    # Assert
    assert result.result == "fail"
    assert result.observed == "0,1,2,7"


def test_open_fds_excludes_the_listing_descriptor(probe):
    # Act
    fds = probe.open_fds()

    # Assert
    assert {0, 1, 2} <= set(fds)
    for fd in fds:
        probe.os.fstat(fd)


@pytest.mark.parametrize(
    ("init", "pgrp", "sid", "expected"),
    [
        ("bwrap", 2, 2, "pass"),
        ("bwrap", 0, 0, "fail"),
        ("bwrap", 2, 0, "fail"),
        ("systemd", 2, 2, "error"),
    ],
)
def test_pgrp_isolated(probe, monkeypatch, init, pgrp, sid, expected):
    # Arrange
    monkeypatch.setattr(
        probe, "open", fake_open({"/proc/1/comm": f"{init}\n"}), raising=False
    )
    monkeypatch.setattr(probe.os, "getpgrp", lambda: pgrp)
    monkeypatch.setattr(probe.os, "getsid", lambda pid: sid)

    # Act / Assert
    assert probe.check_pgrp_isolated("").result == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Name:\tx\nSeccomp:\t2\n", "pass"),
        ("Name:\tx\nSeccomp:\t0\n", "fail"),
        ("Name:\tx\n", "error"),
    ],
)
def test_seccomp_active(probe, monkeypatch, status, expected):
    # Arrange
    monkeypatch.setattr(
        probe, "open", fake_open({"/proc/self/status": status}), raising=False
    )

    # Act / Assert
    assert probe.check_seccomp_active("").result == expected


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ((errno.EPERM, errno.EPERM, errno.EPERM), "pass"),
        ((errno.EPERM, errno.EPERM, errno.EBADF), "fail"),
        ((errno.EBADF, errno.EBADF, errno.EBADF), "fail"),
        ((errno.EPERM, errno.ENOTTY, errno.EPERM), "error"),
    ],
)
def test_tty_ioctl_blocked_classification(probe, monkeypatch, codes, expected):
    # Arrange
    outcomes = iter(codes)
    monkeypatch.setattr(probe, "raw_syscall", lambda name, args: next(outcomes))

    # Act / Assert
    assert probe.check_tty_ioctl_blocked("").result == expected


def test_tty_ioctl_blocked_sets_high_bits_on_the_third_request(probe, monkeypatch):
    # Arrange
    seen = []

    def record(name, args):
        seen.append(args[1])
        return errno.EPERM

    monkeypatch.setattr(probe, "raw_syscall", record)

    # Act
    probe.check_tty_ioctl_blocked("")

    # Assert
    assert seen[2] >> 32 != 0
    assert seen[2] & 0xFFFFFFFF == seen[0]


@pytest.mark.parametrize(
    ("arg", "code", "expected"),
    [
        ("ptrace", errno.EPERM, "pass"),
        ("ptrace", errno.ESRCH, "fail"),
        ("ptrace", errno.EINVAL, "error"),
        ("personality", 0, "fail"),
        ("clone3:ENOSYS", errno.ENOSYS, "pass"),
        ("clone3:ENOSYS", errno.EFAULT, "fail"),
    ],
)
def test_syscall_denied_classification(probe, monkeypatch, arg, code, expected):
    # Arrange
    monkeypatch.setattr(probe, "io_uring_restricted", lambda: None)
    monkeypatch.setattr(probe, "raw_syscall", lambda name, args: code)

    # Act / Assert
    assert probe.check_syscall_denied(arg).result == expected


def test_syscall_denied_unknown_architecture_is_an_error(probe, monkeypatch):
    # Arrange
    monkeypatch.setattr(probe.platform, "machine", lambda: "riscv64")

    # Act
    result = probe.check_syscall_denied("ptrace")

    # Assert
    assert result.result == "error"


@pytest.mark.parametrize(
    ("value", "expected"), [("2", "not-applicable"), ("1", "error")]
)
def test_syscall_denied_io_uring_restricted_by_sysctl(
    probe, monkeypatch, value, expected
):
    # Arrange
    monkeypatch.setattr(probe, "io_uring_restricted", lambda: value)

    # Act / Assert
    assert probe.check_syscall_denied("io_uring_setup").result == expected


def test_main_reports_a_crashing_check_as_error_and_keeps_earlier_results(
    probe, monkeypatch, capsys
):
    # Arrange
    def crash(arg):
        raise OSError(errno.EIO, "boom")

    monkeypatch.setitem(probe.CHECKS, "crash", (crash, None))

    # Act
    status = probe.main(["hidden:/nonexistent-probe-path", "crash"])

    # Assert
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert status == 1
    assert [r["result"] for r in results] == ["pass", "error"]


def test_every_probed_syscall_has_a_number_on_each_architecture(probe):
    # Act / Assert
    for table in probe.SYSCALL_NUMBERS.values():
        assert set(probe.SYSCALL_PROBES) | {"ioctl"} == set(table)


@pytest.mark.skipif(
    platform.machine() not in ("x86_64", "aarch64"),
    reason="raw syscalls need a supported architecture",
)
def test_raw_syscall_reports_an_errno(probe):
    # Act: setns on an invalid descriptor fails with EBADF, or EPERM under a filter
    code = probe.raw_syscall("setns", (-1, 0))

    # Assert
    assert code in (errno.EBADF, errno.EPERM)
