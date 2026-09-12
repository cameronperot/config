"""SSH login hooks and agent selection in persistent Zsh panes."""

import os
import select
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

DOTFILES = Path(__file__).resolve().parent.parent / "dotfiles"
SSH_RC = DOTFILES / ".config/tmux/ssh_rc"
ZSH_AGENT = DOTFILES / ".config/zsh/ssh-agent.zsh"


@pytest.fixture
def agent_env(tmp_path):
    (tmp_path / ".ssh").mkdir(mode=0o700)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "XDG_RUNTIME_DIR": str(runtime),
        "SSH_CONNECTION": "192.0.2.1 12345 192.0.2.2 22",
    }


@pytest.fixture
def agent_sockets(tmp_path):
    with (
        socket.socket(socket.AF_UNIX) as first,
        socket.socket(socket.AF_UNIX) as second,
    ):
        first.bind(str(tmp_path / "first.sock"))
        second.bind(str(tmp_path / "second.sock"))
        first.listen()
        second.listen()
        first.settimeout(5)
        second.settimeout(5)
        yield first, second


@pytest.fixture
def zsh():
    executable = shutil.which("zsh")
    if executable is None:
        pytest.skip("zsh is not installed")
    return executable


def run_rc(env, cookie=""):
    return subprocess.run(
        ["sh", str(SSH_RC)],
        env=env,
        input=cookie,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def run_zsh(zsh, env):
    return subprocess.run(
        [
            zsh,
            "-dfc",
            '. "$1"; print -r -- "${SSH_AUTH_SOCK-UNSET}"',
            "_",
            str(ZSH_AGENT),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )


def test_ssh_rc_latest_login_replaces_link(agent_env, agent_sockets):
    first, second = agent_sockets
    link = Path(agent_env["XDG_RUNTIME_DIR"]) / "ssh-forwarded-agent.sock"
    agent_env["SSH_AUTH_SOCK"] = first.getsockname()
    assert run_rc(agent_env).returncode == 0
    agent_env["SSH_AUTH_SOCK"] = second.getsockname()

    result = run_rc(agent_env)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert link.readlink() == Path(second.getsockname())
    assert sorted(link.parent.iterdir()) == [link]


@pytest.mark.parametrize("initial_forwarding", [False, True])
def test_existing_pane_connects_to_latest_login(
    agent_env, agent_sockets, zsh, initial_forwarding
):
    first, second = agent_sockets
    pane_env = agent_env | {"TMUX": "/tmp/tmux-review,1,0"}
    if initial_forwarding:
        pane_env["SSH_AUTH_SOCK"] = first.getsockname()
        assert run_rc(pane_env).returncode == 0
    command = (
        '. "$1"; print -r -- "$SSH_AUTH_SOCK"; read -r trigger; '
        'zmodload zsh/net/socket; zsocket "$SSH_AUTH_SOCK"'
    )
    with subprocess.Popen(
        [zsh, "-dfc", command, "_", str(ZSH_AGENT)],
        env=pane_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as pane:
        try:
            assert pane.stdout is not None
            assert select.select([pane.stdout], [], [], 5)[0] == [pane.stdout]
            assert pane.stdout.readline().strip() == (
                f"{agent_env['XDG_RUNTIME_DIR']}/ssh-forwarded-agent.sock"
            )

            result = run_rc(agent_env | {"SSH_AUTH_SOCK": second.getsockname()})
            _, stderr = pane.communicate(input="connect\n", timeout=5)

            assert result.returncode == 0
            assert pane.returncode == 0, stderr
            connection, _ = second.accept()
            connection.close()
        finally:
            if pane.poll() is None:
                pane.kill()
                pane.wait(timeout=5)


@pytest.mark.parametrize("session", ["without-forwarding", "container", "stable-path"])
def test_ssh_rc_leaves_link_unchanged(agent_env, agent_sockets, session):
    first, second = agent_sockets
    link = Path(agent_env["XDG_RUNTIME_DIR"]) / "ssh-forwarded-agent.sock"
    link.symlink_to(first.getsockname())
    settings = {
        "without-forwarding": {},
        "container": {"container": "oci", "SSH_AUTH_SOCK": second.getsockname()},
        "stable-path": {"SSH_AUTH_SOCK": str(link)},
    }

    result = run_rc(agent_env | settings[session])

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert link.readlink() == Path(first.getsockname())


def test_ssh_rc_missing_runtime_reports_error(agent_env, agent_sockets):
    first, _ = agent_sockets
    agent_env.pop("XDG_RUNTIME_DIR")
    agent_env["SSH_AUTH_SOCK"] = first.getsockname()

    result = run_rc(agent_env)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "XDG_RUNTIME_DIR is unavailable" in result.stderr


def test_ssh_rc_invalid_socket_preserves_link(agent_env, agent_sockets):
    first, _ = agent_sockets
    link = Path(agent_env["XDG_RUNTIME_DIR"]) / "ssh-forwarded-agent.sock"
    link.symlink_to(first.getsockname())
    agent_env["SSH_AUTH_SOCK"] = str(link.parent / "missing.sock")

    result = run_rc(agent_env)

    assert result.returncode == 1
    assert "is not a socket" in result.stderr
    assert link.readlink() == Path(first.getsockname())


def test_ssh_rc_failed_replace_reports_error_and_cleans_up(agent_env, agent_sockets):
    first, _ = agent_sockets
    link = Path(agent_env["XDG_RUNTIME_DIR"]) / "ssh-forwarded-agent.sock"
    link.mkdir()
    agent_env["SSH_AUTH_SOCK"] = first.getsockname()

    result = run_rc(agent_env)

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""
    assert link.is_dir()
    assert sorted(link.parent.iterdir()) == [link]


@pytest.mark.parametrize("display", ["localhost:10.0", "unix:10.0"])
def test_ssh_rc_installs_x11_cookie_even_if_agent_setup_fails(agent_env, display):
    if shutil.which("xauth") is None:
        pytest.skip("xauth is not installed")
    authority = Path(agent_env["XDG_RUNTIME_DIR"]) / "Xauthority"
    authority.touch(mode=0o600)
    agent_env.update(
        DISPLAY=display,
        XAUTHORITY=str(authority),
        SSH_AUTH_SOCK=str(authority.parent / "missing.sock"),
    )
    cookie = "0123456789abcdef0123456789abcdef"

    result = run_rc(agent_env, cookie=f"MIT-MAGIC-COOKIE-1 {cookie}\n")

    listing = subprocess.run(
        ["xauth", "-f", str(authority), "list"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert f"MIT-MAGIC-COOKIE-1  {cookie}" in listing.stdout


@pytest.mark.parametrize("in_tmux", [False, True])
def test_zsh_never_repoints_latest_link(agent_env, agent_sockets, zsh, in_tmux):
    first, second = agent_sockets
    link = Path(agent_env["XDG_RUNTIME_DIR"]) / "ssh-forwarded-agent.sock"
    link.symlink_to(second.getsockname())
    agent_env["SSH_AUTH_SOCK"] = first.getsockname()
    if in_tmux:
        agent_env["TMUX"] = "/tmp/tmux-review,1,0"

    result = run_zsh(zsh=zsh, env=agent_env)

    assert result.stdout.strip() == (str(link) if in_tmux else first.getsockname())
    assert link.readlink() == Path(second.getsockname())


def test_zsh_remote_without_forwarding_stays_unset(agent_env, zsh):
    result = run_zsh(zsh=zsh, env=agent_env)

    assert result.stdout == "UNSET\n"


def test_zsh_missing_runtime_keeps_forwarded_socket_with_warning(agent_env, zsh):
    agent_env.pop("XDG_RUNTIME_DIR")
    agent_env.update(TMUX="/tmp/tmux-review,1,0", SSH_AUTH_SOCK="/tmp/forwarded.sock")

    result = run_zsh(zsh=zsh, env=agent_env)

    assert result.stdout == "/tmp/forwarded.sock\n"
    assert "XDG_RUNTIME_DIR is unavailable" in result.stderr


@pytest.mark.parametrize("forwarded", [False, True])
def test_zsh_container_preserves_supplied_socket(agent_env, zsh, forwarded):
    agent_env["container"] = "oci"
    if forwarded:
        agent_env["SSH_AUTH_SOCK"] = "/tmp/signing.sock"

    result = run_zsh(zsh=zsh, env=agent_env)

    assert result.stdout == ("/tmp/signing.sock\n" if forwarded else "UNSET\n")
    assert result.stderr == ""


def test_zsh_local_selects_personal_agent(agent_env, agent_sockets, zsh):
    first, _ = agent_sockets
    agent_env.pop("SSH_CONNECTION")
    personal = Path(agent_env["XDG_RUNTIME_DIR"]) / "ssh-agent.sock"
    personal.symlink_to(first.getsockname())

    result = run_zsh(zsh=zsh, env=agent_env)

    assert result.stdout.strip() == str(personal)
    assert result.stderr == ""
