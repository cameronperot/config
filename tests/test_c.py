"""Tests for dotfiles/bin/c: mounts, container selection, argv assembly and the CLI."""

import argparse
import importlib.util
import io
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import sys
import threading
import types
from collections.abc import Callable, Iterator
from importlib.machinery import SourceFileLoader
from itertools import pairwise
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "dotfiles" / "bin" / "c"
CONFIG_DIR = Path("/cfg")
SSH_SOCK = Path("/run/user/7/llm-agent.sock")
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def load_script() -> types.ModuleType:
    """Load the extensionless script as a module.

    Returns:
        The script's namespace. Bytecode writing is disabled while loading so no
            ``__pycache__`` lands in ``dotfiles/bin/``, which ``install.py`` rsyncs.
    """
    loader = SourceFileLoader("c", str(SCRIPT))
    spec = importlib.util.spec_from_loader("c", loader)
    assert spec is not None, f"failed to create import spec for {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module


c = load_script()


def git(*args: str) -> None:
    """Run git with a fixed identity and no user or system config.

    Args:
        *args: Arguments after ``git``.
    """
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        check=True,
        env=GIT_ENV,
        capture_output=True,
    )


def commit_repo(repo: Path) -> None:
    """Initialize ``repo`` and commit one file on ``main``.

    Args:
        repo: Existing directory to turn into a repository.
    """
    (repo / "f").write_text("")
    git("init", "-q", str(repo))
    git("-C", str(repo), "add", "-A")
    git("-C", str(repo), "commit", "-qm", "init")


@pytest.fixture
def plain_repo(tmp_path: Path) -> Path:
    """A plain repository with an untracked ``sub/`` directory.

    Args:
        tmp_path: Pytest temporary directory root.

    Returns:
        The resolved repository root.
    """
    repo = tmp_path.resolve() / "plain"
    (repo / "sub").mkdir(parents=True)
    commit_repo(repo)
    return repo


@pytest.fixture
def bare_layout(tmp_path: Path) -> Path:
    """A ``.bare`` layout: ``d/{.bare, .git, main/sub, feature}`` plus ``../outside``.

    Args:
        tmp_path: Pytest temporary directory root.

    Returns:
        The resolved directory ``d`` holding ``.bare``.
    """
    root = tmp_path.resolve()
    src = root / "src"
    src.mkdir()
    commit_repo(src)
    d = root / "d"
    d.mkdir()
    git("clone", "-q", "--bare", str(src), str(d / ".bare"))
    (d / ".git").write_text("gitdir: ./.bare\n")
    git("-C", str(d), "worktree", "add", "-q", str(d / "main"), "main")
    (d / "main" / "sub").mkdir()
    git(
        "-C",
        str(d / "main"),
        "worktree",
        "add",
        "-q",
        str(d / "feature"),
        "-b",
        "feature",
    )
    git(
        "-C",
        str(d / "main"),
        "worktree",
        "add",
        "-q",
        str(root / "outside"),
        "-b",
        "outside",
    )
    return d


@pytest.fixture
def tmp_sock_dir(tmp_path: Path) -> Path:
    """A temp directory holding a bound ``llm-agent.sock``.

    Args:
        tmp_path: Pytest temporary directory root.

    Returns:
        The resolved directory with the socket.
    """
    runtime = tmp_path.resolve() / "run"
    runtime.mkdir()
    bind_unix_socket(runtime / "llm-agent.sock")
    return runtime


@pytest.fixture
def signer_server() -> Iterator[Callable[[bytes | None], int]]:
    """Serve one ssh-agent reply over TCP.

    Yields:
        A factory taking the reply bytes (None = accept and close without
            replying) and returning the listening port; the server answers a
            single connection and then closes.
    """
    servers: list[socket.socket] = []

    def factory(reply: bytes | None) -> int:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind((LOCAL_HOST, 0))
        srv.listen(1)
        servers.append(srv)
        port = srv.getsockname()[1]

        def serve() -> None:
            try:
                conn, _ = srv.accept()
                with conn:
                    conn.recv(5)
                    if reply is not None:
                        conn.sendall(reply)
            except OSError:
                pass

        threading.Thread(target=serve, daemon=True).start()
        return port

    yield factory
    for srv in servers:
        srv.close()


def bind_unix_socket(path: Path) -> None:
    """Bind a unix socket at ``path``.

    Args:
        path: Path to bind the socket at; the parent directory must exist.
    """
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(path))
    finally:
        sock.close()


def agent_identity_reply(keys: int) -> bytes:
    """Build an ``SSH_AGENTC_REQUEST_IDENTITIES_ANSWER`` reporting ``keys`` keys.

    Args:
        keys: Key count to report.

    Returns:
        The 4-byte big-endian length, the answer type byte (12), and the
            4-byte big-endian key count.
    """
    payload = bytes([12]) + struct.pack(">I", keys)
    return struct.pack(">I", len(payload)) + payload


def closed_tcp_port() -> int:
    """Return a loopback port with nothing listening on it.

    Returns:
        The port number.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def usable_tcp_host() -> str:
    """Return a local TCP address that reaches listeners bound on it.

    Prefers ``127.0.0.1``. When a loopback self-connect is refused — sandboxed
    networks can intercept loopback — the first other local address from the
    routing table is used so fake signers stay reachable.

    Returns:
        The address to bind fake signers on and connect probes to.
    """
    candidates = ["127.0.0.1"]
    try:
        lines = Path("/proc/net/fib_trie").read_text().splitlines()
    except OSError:
        lines = []
    for previous, line in pairwise(lines):
        if "/32 host LOCAL" not in line:
            continue
        match = re.fullmatch(r"\s*\|-- (\d+\.\d+\.\d+\.\d+)", previous)
        if match and not match[1].startswith("127.") and match[1] not in candidates:
            candidates.append(match[1])
    for host in candidates:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind((host, 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(1.0)
            reachable = probe.connect_ex((host, port)) == 0
            probe.close()
            srv.close()
        except OSError:
            continue
        if reachable:
            return host
    return "127.0.0.1"


LOCAL_HOST = usable_tcp_host()


def mount(source: str, destination: str = "/work") -> c.Mount:
    """Build a ``Mount`` from path strings.

    Args:
        source: Host path.
        destination: Container path.

    Returns:
        The mount.
    """
    return c.Mount(source=Path(source), destination=Path(destination))


def container(name: str, *mounts: c.Mount, id: str = "0123456789abcdef") -> c.Container:
    """Build a ``Container`` from its name and mounts.

    Args:
        name: Container name.
        *mounts: Bind mounts, possibly none.
        id: Container id.

    Returns:
        The container.
    """
    return c.Container(id=id, name=name, mounts=mounts)


def install_fake_podman(bin_dir: Path, containers: list[dict] | None) -> None:
    """Write a fake ``podman`` into ``bin_dir``.

    Args:
        bin_dir: Directory to create; prepend it to ``PATH``.
        containers: ``podman inspect`` entries, also listed by ``ps -q``; None
            installs a fake that exits 125 with an error on stderr instead.
    """
    bin_dir.mkdir()
    if containers is None:
        body = 'echo "Error: cannot connect" >&2\nexit 125\n'
    else:
        (bin_dir / "ps.txt").write_text(
            "".join(f"{info['Id']}\n" for info in containers)
        )
        (bin_dir / "inspect.json").write_text(json.dumps(containers))
        body = (
            'case "$1" in\n'
            f'  ps) cat "{bin_dir}/ps.txt" ;;\n'
            f'  inspect) cat "{bin_dir}/inspect.json" ;;\n'
            "esac\n"
        )
    script = bin_dir / "podman"
    script.write_text(f"#!/usr/bin/env bash\n{body}")
    script.chmod(0o755)


def inspect_entry(name: str, source: Path, destination: str = "/work") -> dict:
    """Build a ``podman inspect`` entry with one bind mount and one volume.

    Args:
        name: Container name.
        source: Host path of the bind mount.
        destination: Container path of the bind mount.

    Returns:
        The entry, with ``Id`` derived from ``name``.
    """
    return {
        "Id": f"{abs(hash(name)):016x}",
        "Name": name,
        "Mounts": [
            {"Type": "bind", "Source": str(source), "Destination": destination},
            {
                "Type": "volume",
                "Source": "/var/lib/v",
                "Destination": "/home/user/.antidote",
            },
        ],
    }


# --- resolve_mounts


def test_resolve_mounts_outside_git_is_cwd(tmp_path: Path) -> None:
    nogit = tmp_path.resolve() / "nogit"
    nogit.mkdir()

    assert c.resolve_workspace(nogit).mounts == (nogit,)


def test_resolve_mounts_plain_repo_is_toplevel(plain_repo: Path) -> None:
    assert c.resolve_workspace(plain_repo / "sub").mounts == (plain_repo,)


def test_resolve_mounts_linked_worktree_adds_common_dir(plain_repo: Path) -> None:
    worktree = plain_repo.parent / "plain-wt"
    git("-C", str(plain_repo), "worktree", "add", "-q", str(worktree), "-b", "wt")

    assert c.resolve_workspace(worktree).mounts == (worktree, plain_repo / ".git")


def test_resolve_mounts_bare_layout_worktrees_map_to_parent(bare_layout: Path) -> None:
    assert c.resolve_workspace(bare_layout / "main" / "sub").mounts == (bare_layout,)
    assert c.resolve_workspace(bare_layout / "feature").mounts == (bare_layout,)


def test_resolve_mounts_bare_layout_parent_is_itself(bare_layout: Path) -> None:
    assert c.resolve_workspace(bare_layout).mounts == (bare_layout,)


def test_resolve_mounts_bare_layout_outside_worktree_adds_toplevel(
    bare_layout: Path,
) -> None:
    outside = bare_layout.parent / "outside"

    assert c.resolve_workspace(outside).mounts == (bare_layout, outside)


# --- check_mount_allowed


def test_check_mount_allowed_refuses_home_and_ancestors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path.resolve() / "users" / "me"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    for path in (home, home.parent, Path("/")):
        with pytest.raises(c.Error, match="refusing to mount"):
            c.check_mount_allowed(path)


def test_check_mount_allowed_accepts_paths_under_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path.resolve() / "home"
    project = home / "projects" / "x"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    c.check_mount_allowed(project)


# --- select_container


def test_select_container_prefers_dev_container_over_deeper_mount() -> None:
    other = container("other", mount("/srv/proj/sub"))
    preferred = container("dev_container", mount("/srv"))

    chosen, chosen_mount = c.select_container(
        cwd=Path("/srv/proj/sub/x"), containers=(other, preferred), name=None
    )

    assert chosen is preferred
    assert chosen_mount == mount("/srv")


def test_select_container_picks_deepest_mount() -> None:
    shallow = container("a", mount("/srv"))
    deep = container("b", mount("/srv/proj", "/proj"))

    chosen, chosen_mount = c.select_container(
        cwd=Path("/srv/proj/x"), containers=(shallow, deep), name=None
    )

    assert chosen is deep
    assert chosen_mount.translate(Path("/srv/proj/x")) == Path("/proj/x")


def test_select_container_first_wins_on_ties() -> None:
    first = container("a", mount("/srv"))
    second = container("b", mount("/srv"))

    chosen, _ = c.select_container(
        cwd=Path("/srv/x"), containers=(first, second), name=None
    )

    assert chosen is first


def test_select_container_filters_by_name_or_id_prefix() -> None:
    a = container("a", mount("/srv"), id="aaaa1111")
    b = container("b", mount("/srv/proj"), id="bbbb2222")

    by_name, _ = c.select_container(cwd=Path("/srv/proj"), containers=(a, b), name="a")
    by_id, _ = c.select_container(cwd=Path("/srv/proj"), containers=(a, b), name="bbbb")

    assert by_name is a
    assert by_id is b


def test_select_container_errors() -> None:
    mountless = container("x")
    containers = (mountless, container("y", mount("/srv")))

    with pytest.raises(c.Error, match=r"^no running containers$"):
        c.select_container(cwd=Path("/srv"), containers=(), name=None)
    with pytest.raises(c.Error, match=r"^no running container named 'nope'$"):
        c.select_container(cwd=Path("/srv"), containers=containers, name="nope")
    with pytest.raises(c.Error, match=r"^no bind mount in 'x' contains /srv$"):
        c.select_container(cwd=Path("/srv"), containers=containers, name="x")
    with pytest.raises(
        c.Error, match=r"^no bind mount in any running container contains /tmp$"
    ):
        c.select_container(cwd=Path("/tmp"), containers=containers, name=None)


# --- argv builders


def run_argv(**overrides: object) -> list[str]:
    """Call ``c.run_argv`` with plain-container defaults.

    Args:
        **overrides: Keyword arguments replacing the defaults.

    Returns:
        The assembled argv.
    """
    kwargs: dict[str, object] = {
        "cwd": Path("/srv/proj/sub"),
        "mounts": (Path("/srv/proj"),),
        "agent_config_dir": CONFIG_DIR,
        "ssh_sock": SSH_SOCK,
        "krun": False,
        "cpus": None,
        "ram_mib": None,
        "plannotator_port": None,
        "extra_args": [],
        "tty": False,
        "command": ["bash"],
        "signing_disabled": False,
    }
    return c.run_argv(**(kwargs | overrides))


EXPECTED_HEAD = [
    *(
        "podman",
        "run",
        "--rm",
        "--userns",
        "keep-id",
        "--security-opt",
        "label=disable",
    ),
    *("-w", "/srv/proj/sub", "-v", "/srv/proj:/srv/proj"),
    *("-v", "/cfg/.agent:/home/user/.agent"),
    *("-v", "/cfg/.pi/agent:/home/user/.pi/agent"),
    *("-v", "/cfg/.omp/agent:/home/user/.omp/agent"),
    *("-v", "/cfg/.agent/skills:/home/user/.pi/agent/skills"),
    *("-v", "/cfg/.agent/skills:/home/user/.omp/agent/skills"),
    *("-v", "/cfg/.agent/prompts:/home/user/.pi/agent/prompts"),
    *("-v", "/cfg/.agent/prompts:/home/user/.omp/agent/prompts"),
    *("-v", "/cfg/.plannotator:/home/user/.plannotator"),
    *("-v", "/cfg/.opencode:/home/user/.opencode"),
    *("-v", "/cfg/.config/opencode:/home/user/.config/opencode"),
    *("-v", "/cfg/.local/share/opencode:/home/user/.local/share/opencode"),
    *("-v", "/cfg/.local/state/opencode:/home/user/.local/state/opencode"),
    *("-v", "/cfg/.local/share/opentui:/home/user/.local/share/opentui"),
    *("-v", "/cfg/.claude:/home/user/.claude"),
    *("-v", "/cfg/.local/state/claude:/home/user/.local/state/claude"),
    *("-v", "dev-pre-commit:/home/user/.cache/pre-commit"),
]
SSH_ENV = ["-e", "SSH_AUTH_SOCK=/tmp/ssh-agent.sock"]
SOCKET_MOUNT = ["-v", "/run/user/7/llm-agent.sock:/tmp/ssh-agent.sock"]
SIGNING_OFF_ENV = [
    "-e",
    "GIT_CONFIG_COUNT=1",
    "-e",
    "GIT_CONFIG_KEY_0=commit.gpgsign",
    "-e",
    "GIT_CONFIG_VALUE_0=false",
    "-e",
    "GIT_SIGNING_DISABLED=1",
]


@pytest.mark.parametrize("krun", (False, True), ids=("plain", "krun"))
def test_run_argv_mounts_pre_commit_cache_once_before_image(krun: bool) -> None:
    argv = run_argv(krun=krun, cpus=4, ram_mib=8192)

    volume = "dev-pre-commit:/home/user/.cache/pre-commit"
    assert argv.count(volume) == 1
    index = argv.index(volume)
    assert argv[index - 1] == "-v"
    assert index < argv.index("dev:latest")


def test_run_argv_plain_container() -> None:
    assert run_argv() == [
        *EXPECTED_HEAD,
        *SSH_ENV,
        *SOCKET_MOUNT,
        "-i",
        "dev:latest",
        "bash",
    ]


def test_run_argv_without_socket_omits_ssh_env_and_mount() -> None:
    argv = run_argv(ssh_sock=None)

    assert argv == [*EXPECTED_HEAD, "-i", "dev:latest", "bash"]


def test_run_argv_plain_container_limits_only_when_set() -> None:
    both = run_argv(cpus=2, ram_mib=1024)
    ram_only = run_argv(ram_mib=512)

    assert both[len(EXPECTED_HEAD) :] == [
        *SSH_ENV,
        *SOCKET_MOUNT,
        "--cpus",
        "2",
        "--memory",
        "1024m",
        "-i",
        "dev:latest",
        "bash",
    ]
    assert ram_only[len(EXPECTED_HEAD) :] == [
        *SSH_ENV,
        *SOCKET_MOUNT,
        "--memory",
        "512m",
        "-i",
        "dev:latest",
        "bash",
    ]


def test_run_argv_krun_uses_annotations_and_tcp_bridge() -> None:
    argv = run_argv(krun=True, cpus=4, ram_mib=8192)

    assert argv[len(EXPECTED_HEAD) :] == [
        *SSH_ENV,
        *("--runtime=krun", "--network", "pasta:-T,7777"),
        *("--annotation", "krun.cpus=4", "--annotation", "krun.ram_mib=8192"),
        "-i",
        "dev:latest",
        "bash",
    ]
    assert "--cpus" not in argv
    assert "--memory" not in argv


def test_run_argv_extra_args_precede_tty_flags_and_image() -> None:
    argv = run_argv(extra_args=["--network=host"], tty=True, command=[])

    assert argv[len(EXPECTED_HEAD) :] == [
        *SSH_ENV,
        *SOCKET_MOUNT,
        "--network=host",
        "-i",
        "-t",
        "dev:latest",
    ]


def test_run_argv_publishes_plannotator_port_on_both_networks() -> None:
    publish = [
        *(
            "-p",
            "127.0.0.1:19555:19555",
            "-e",
            "PLANNOTATOR_REMOTE=1",
            "-e",
            "PLANNOTATOR_PORT=19555",
        )
    ]

    assert run_argv(plannotator_port=19555) == [
        *EXPECTED_HEAD,
        *SSH_ENV,
        *SOCKET_MOUNT,
        *publish,
        "-i",
        "dev:latest",
        "bash",
    ]
    assert run_argv(krun=True, cpus=4, ram_mib=8192, plannotator_port=19555)[
        len(EXPECTED_HEAD) :
    ] == [
        *SSH_ENV,
        *("--runtime=krun", "--network", "pasta:-T,7777"),
        *("--annotation", "krun.cpus=4", "--annotation", "krun.ram_mib=8192"),
        *publish,
        "-i",
        "dev:latest",
        "bash",
    ]


def test_run_argv_signing_disabled_appends_git_config() -> None:
    with_socket = run_argv(signing_disabled=True)
    without_socket = run_argv(ssh_sock=None, signing_disabled=True)

    assert with_socket[len(EXPECTED_HEAD) :] == [
        *SIGNING_OFF_ENV,
        "-i",
        "dev:latest",
        "bash",
    ]
    assert without_socket[len(EXPECTED_HEAD) :] == [
        *SIGNING_OFF_ENV,
        "-i",
        "dev:latest",
        "bash",
    ]


def test_run_argv_signing_disabled_under_krun() -> None:
    argv = run_argv(krun=True, cpus=4, ram_mib=8192, signing_disabled=True)

    assert argv[len(EXPECTED_HEAD) :] == [
        *("--runtime=krun", "--network", "pasta"),
        *("--annotation", "krun.cpus=4", "--annotation", "krun.ram_mib=8192"),
        *SIGNING_OFF_ENV,
        "-i",
        "dev:latest",
        "bash",
    ]


def test_pick_free_port_yields_bindable_loopback_port() -> None:
    port = c.pick_free_port()

    assert isinstance(port, int)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


# --- probe_tcp_signer


def test_probe_tcp_signer_accepts_nonempty_identity_reply(
    signer_server: Callable[[bytes | None], int],
) -> None:
    assert c.probe_tcp_signer(LOCAL_HOST, signer_server(agent_identity_reply(2)))


def test_probe_tcp_signer_rejects_empty_identity_reply(
    signer_server: Callable[[bytes | None], int],
) -> None:
    assert not c.probe_tcp_signer(LOCAL_HOST, signer_server(agent_identity_reply(0)))


def test_probe_tcp_signer_rejects_malformed_reply(
    signer_server: Callable[[bytes | None], int],
) -> None:
    bad = b"\x00\x00\x00\x02\x05\x00"  # type 5 is not the identities answer

    assert not c.probe_tcp_signer(LOCAL_HOST, signer_server(bad))


def test_probe_tcp_signer_rejects_closed_connection(
    signer_server: Callable[[bytes | None], int],
) -> None:
    assert not c.probe_tcp_signer(LOCAL_HOST, signer_server(None))


def test_probe_tcp_signer_rejects_closed_port() -> None:
    assert not c.probe_tcp_signer(LOCAL_HOST, closed_tcp_port())


def test_exec_argv() -> None:
    interactive = c.exec_argv(
        name="dev_container", workdir=Path("/work/sub"), tty=True, command=["bash"]
    )
    batch = c.exec_argv(
        name="dev_container", workdir=Path("/work"), tty=False, command=["ls"]
    )

    assert interactive == [
        "podman",
        "exec",
        "-w",
        "/work/sub",
        "-i",
        "-t",
        "dev_container",
        "bash",
    ]
    assert batch == ["podman", "exec", "-w", "/work", "-i", "dev_container", "ls"]


# --- parser and usage_errors


def parse(*argv: str) -> argparse.Namespace:
    """Parse ``argv`` with the script's parser.

    Args:
        *argv: Command-line arguments.

    Returns:
        The parsed namespace, before ``main``'s ``-c`` implies ``-r`` step.
    """
    return c.build_parser().parse_args(list(argv))


def test_parser_accepts_option_like_extra_args() -> None:
    args = parse("-a=--network=host", "--arg=--cap-add=X", "bash")

    assert args.arg == ["--network=host", "--cap-add=X"]
    assert args.command == ["bash"]


def test_parser_passes_command_flags_through() -> None:
    args = parse("-r", "bash", "-c", "echo hi")

    assert args.command == ["bash", "-c", "echo hi"]
    assert args.container is None


def test_usage_errors_lists_every_new_container_flag_given_with_running() -> None:
    args = parse("-r", "-k", "-a=x", "--cpus", "1", "--no-git-signing", "--ngr", "bash")

    assert c.usage_errors(args) == (
        "-k/--krun, -a/--arg, --cpus, --no-git-signing/--ngs, "
        "--no-git-root/--ngr cannot be used with -r/--running",
    )


def test_usage_errors_reports_missing_command_alongside_conflicts() -> None:
    assert c.usage_errors(parse("-r")) == ("no command specified",)
    assert c.usage_errors(parse("-r", "--ram-mib", "5")) == (
        "--ram-mib cannot be used with -r/--running",
        "no command specified",
    )


def test_usage_errors_accepts_new_container_combinations() -> None:
    assert c.usage_errors(parse()) == ()
    assert c.usage_errors(parse("--cpus", "2", "bash")) == ()
    assert c.usage_errors(parse("-k", "--ram-mib", "1024", "-a=--net=host")) == ()
    assert c.usage_errors(parse("--plannotator-port", "19555", "bash")) == ()
    assert c.usage_errors(parse("--no-plannotator-port", "bash")) == ()


def test_usage_errors_rejects_plannotator_flag_combinations() -> None:
    assert c.usage_errors(
        parse("--plannotator-port", "1", "--no-plannotator-port", "bash")
    ) == ("--plannotator-port and --no-plannotator-port are mutually exclusive",)
    assert c.usage_errors(parse("-r", "--plannotator-port", "1", "bash")) == (
        "--plannotator-port cannot be used with -r/--running",
    )
    assert c.usage_errors(parse("-r", "--no-plannotator-port", "bash")) == (
        "--no-plannotator-port cannot be used with -r/--running",
    )


def test_parser_reads_plannotator_flags() -> None:
    override = parse("--plannotator-port", "19555", "bash")
    opt_out = parse("--no-plannotator-port", "bash")

    assert (override.plannotator_port, override.no_plannotator_port) == (19555, False)
    assert (opt_out.plannotator_port, opt_out.no_plannotator_port) == (None, True)


def test_parser_reads_no_git_signing_flag() -> None:
    default = parse("bash")
    opt_out = parse("--no-git-signing", "bash")

    assert (default.no_git_signing, opt_out.no_git_signing) == (False, True)
    assert parse("--ngs", "bash").no_git_signing is True


def test_parser_reads_no_git_root_flag() -> None:
    default = parse("bash")
    opt_out = parse("--no-git-root", "bash")

    assert (default.no_git_root, opt_out.no_git_root) == (False, True)
    assert parse("--ngr", "bash").no_git_root is True


# --- main


@pytest.fixture
def batch_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace stdin with a non-tty stream so ``main`` never adds ``-i -t``."""
    monkeypatch.setattr(sys, "stdin", io.StringIO())


def test_main_dry_run_prints_run_argv(
    agent_config: Path,
    plain_repo: Path,
    tmp_sock_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_sock_dir))
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    c.main(["--dry-run", "--cpus", "2", "bash", "-c", "echo hi"])

    read = capsys.readouterr()
    assert read.out.startswith(
        "podman run --rm --userns keep-id --security-opt label=disable "
    )
    words = shlex.split(read.out)
    assert words[words.index("-w") + 1] == str(plain_repo / "sub")
    assert f"{plain_repo}:{plain_repo}" in words
    assert f"{agent_config}/.agent:/home/user/.agent" in words
    assert read.out.endswith(
        f" -v {tmp_sock_dir}/llm-agent.sock:/tmp/ssh-agent.sock --cpus 2 "
        "-p 127.0.0.1:19555:19555 -e PLANNOTATOR_REMOTE=1 -e PLANNOTATOR_PORT=19555 "
        "-i dev:latest bash -c 'echo hi'\n"
    )
    assert " -e SSH_AUTH_SOCK=/tmp/ssh-agent.sock " in read.out
    assert "warning" not in read.err


@pytest.mark.parametrize(
    "config_env", [{}, {"AGENT_CONFIG_DIR": ""}], ids=["unset", "empty"]
)
def test_main_dry_run_without_agent_config_omits_config_mounts(
    plain_repo: Path, config_env: dict[str, str]
) -> None:
    env = {key: value for key, value in os.environ.items() if key != "AGENT_CONFIG_DIR"}
    env.update(config_env)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--no-git-signing",
            "--no-plannotator-port",
            "bash",
        ],
        cwd=plain_repo / "sub",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    argv = shlex.split(result.stdout)
    assert [value for flag, value in pairwise(argv) if flag == "-v"] == [
        f"{plain_repo}:{plain_repo}",
        "dev-pre-commit:/home/user/.cache/pre-commit",
    ]
    assert argv[:3] == ["podman", "run", "--rm"]
    assert argv[-2:] == ["dev:latest", "bash"]
    assert result.stderr == ""


def test_main_dry_run_no_git_root_mounts_cwd_only(
    agent_config: Path,
    plain_repo: Path,
    tmp_sock_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_sock_dir))
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    c.main(["--dry-run", "--no-git-root", "bash"])

    read = capsys.readouterr()
    assert f" -w {plain_repo / 'sub'}" in read.out
    assert f" -v {plain_repo / 'sub'}:{plain_repo / 'sub'} " in read.out
    assert f" -v {plain_repo}:{plain_repo} " not in read.out


def test_main_dry_run_missing_socket_warns(
    agent_config: Path,
    plain_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    empty = tmp_path.resolve() / "run"
    empty.mkdir()
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(empty))
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    c.main(["--dry-run", "bash"])

    read = capsys.readouterr()
    assert "llm-agent.sock" not in read.out
    assert "SSH_AUTH_SOCK" not in read.out
    assert (
        f"c: warning: {empty / 'llm-agent.sock'}: signing agent socket not found; "
        "running without ssh-agent\n" in read.err
    )


def test_main_dry_run_krun_signer_reachable_no_warning(
    agent_config: Path,
    plain_repo: Path,
    signer_server: Callable[[bytes | None], int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    port = signer_server(agent_identity_reply(1))
    monkeypatch.setattr(c, "KRUN_SSH_PORT", port)
    monkeypatch.setattr(c, "SSH_PROBE_HOST", LOCAL_HOST)
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))

    c.main(["--dry-run", "-k", "bash"])

    read = capsys.readouterr()
    assert (
        f" --runtime=krun --network pasta:-T,{port} --annotation krun.cpus=4 "
        "--annotation krun.ram_mib=8192 " in read.out
    )
    assert "warning" not in read.err


def test_main_dry_run_krun_missing_signer_warns(
    agent_config: Path,
    plain_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    port = closed_tcp_port()
    monkeypatch.setattr(c, "KRUN_SSH_PORT", port)
    monkeypatch.setattr(c, "SSH_PROBE_HOST", LOCAL_HOST)
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))

    c.main(["--dry-run", "-k", "bash"])

    read = capsys.readouterr()
    assert (
        f" --runtime=krun --network pasta:-T,{port} --annotation krun.cpus=4 "
        "--annotation krun.ram_mib=8192 " in read.out
    )
    assert "llm-agent.sock" not in read.out
    assert (
        f"c: warning: {LOCAL_HOST}:{port}: no signer responded; "
        "bridge remains configured\n" in read.err
    )


def test_main_dry_run_no_git_signing_flag_without_socket(
    agent_config: Path,
    plain_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    empty = tmp_path.resolve() / "run"
    empty.mkdir()
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(empty))
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    c.main(["--dry-run", "--no-git-signing", "bash"])

    read = capsys.readouterr()
    assert "llm-agent.sock" not in read.out
    assert "SSH_AUTH_SOCK" not in read.out
    assert (
        " -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=commit.gpgsign "
        "-e GIT_CONFIG_VALUE_0=false " in read.out
    )
    assert "warning" not in read.err


def test_main_dry_run_git_signing_disabled_env_without_socket(
    agent_config: Path,
    plain_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    empty = tmp_path.resolve() / "run"
    empty.mkdir()
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(empty))
    monkeypatch.setenv("GIT_SIGNING_DISABLED", "1")
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    c.main(["--dry-run", "bash"])

    read = capsys.readouterr()
    assert "llm-agent.sock" not in read.out
    assert "SSH_AUTH_SOCK" not in read.out
    assert (
        " -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=commit.gpgsign "
        "-e GIT_CONFIG_VALUE_0=false " in read.out
    )
    assert "warning" not in read.err


def test_main_dry_run_no_git_signing_skips_present_socket(
    agent_config: Path,
    plain_repo: Path,
    tmp_sock_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_sock_dir))
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    c.main(["--dry-run", "--no-git-signing", "bash"])

    read = capsys.readouterr()
    assert "llm-agent.sock" not in read.out
    assert "SSH_AUTH_SOCK" not in read.out
    assert " -e GIT_CONFIG_COUNT=1 " in read.out
    assert "warning" not in read.err


def test_main_dry_run_krun_no_git_signing_skips_probe(
    agent_config: Path,
    plain_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    port = closed_tcp_port()
    monkeypatch.setattr(c, "KRUN_SSH_PORT", port)
    monkeypatch.setattr(c, "SSH_PROBE_HOST", LOCAL_HOST)
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))

    c.main(["--dry-run", "-k", "--no-git-signing", "bash"])

    read = capsys.readouterr()
    assert " --runtime=krun --network pasta " in read.out
    assert f"pasta:-T,{port}" not in read.out
    assert (
        " -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=commit.gpgsign "
        "-e GIT_CONFIG_VALUE_0=false " in read.out
    )
    assert " -e GIT_SIGNING_DISABLED=1 " in read.out
    assert "warning" not in read.err


def test_new_container_banner_advertises_plan_ui(
    agent_config: Path, plain_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(plain_repo / "sub")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setattr(c, "pick_free_port", lambda: 19555)

    args = c.build_parser().parse_args(["bash"])
    cmd, _ = c.new_container(args, cwd=Path(plain_repo / "sub"), tty=False)

    assert cmd[cmd.index("-p") : cmd.index("-p") + 2] == ["-p", "127.0.0.1:19555:19555"]


def test_main_plannotator_port_flags(
    agent_config: Path,
    plain_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    monkeypatch.chdir(plain_repo)
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))

    c.main(["--dry-run", "--plannotator-port", "19999", "bash"])
    override = capsys.readouterr().out
    assert " -p 127.0.0.1:19999:19999 -e PLANNOTATOR_REMOTE=1 " in override
    assert "-e PLANNOTATOR_PORT=19999 " in override

    c.main(["--dry-run", "--no-plannotator-port", "bash"])
    opt_out = capsys.readouterr().out
    assert "127.0.0.1:" not in opt_out
    assert "PLANNOTATOR" not in opt_out


def test_main_strips_one_command_separator(
    agent_config: Path,
    plain_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    monkeypatch.chdir(plain_repo)
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))

    c.main(["--dry-run", "--", "--", "--version"])

    assert capsys.readouterr().out.endswith(" dev:latest -- --version\n")


def test_main_container_implies_running(
    plain_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    batch_stdin: None,
) -> None:
    bin_dir = tmp_path / "bin"
    install_fake_podman(
        bin_dir,
        [
            inspect_entry("other", plain_repo.parent),
            inspect_entry("dev_container", plain_repo),
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.chdir(plain_repo / "sub")

    c.main(["-c", "dev_container", "--dry-run", "zsh", "-c", "ls -la"])
    c.main(["-r", "--dry-run", "bash"])

    selected_id = inspect_entry("dev_container", plain_repo)["Id"]
    assert capsys.readouterr().out == (
        f"podman exec -w /work/sub -i {selected_id} zsh -c 'ls -la'\n"
        f"podman exec -w /work/sub -i {selected_id} bash\n"
    )


def test_main_reports_missing_podman(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    with pytest.raises(SystemExit) as exc:
        c.main(["-r", "--dry-run", "bash"])

    assert exc.value.code == 127
    assert capsys.readouterr().err == "c: error: podman: No such file or directory\n"


def test_main_reports_engine_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    bin_dir = tmp_path / "bin"
    install_fake_podman(bin_dir, None)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    with pytest.raises(SystemExit) as exc:
        c.main(["-r", "--dry-run", "bash"])

    assert exc.value.code == 1
    assert capsys.readouterr().err == "c: error: podman failed: Error: cannot connect\n"


def test_main_usage_error_exits_with_two(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        c.main(["-r", "-k"])

    assert exc.value.code == 2
    assert (
        "-k/--krun cannot be used with -r/--running; no command specified"
        in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "value, expected",
    [(v, True) for v in ("1", "true", "TRUE", "yes", "YES", "on", "ON")]
    + [(v, False) for v in ("", "0", "false", "FALSE", "no", "NO", "off", "OFF")],
)
def test_boolean_and_dry_run_contract_signing_values(
    monkeypatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("GIT_SIGNING_DISABLED", value)
    assert c.env_bool("GIT_SIGNING_DISABLED") is expected


def test_boolean_and_dry_run_contract_invalid_before_launch(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("GIT_SIGNING_DISABLED", "invalid")
    with pytest.raises(SystemExit) as error:
        c.main(["--dry-run", "--no-git-signing", "bash"])
    assert error.value.code == 2
    assert "GIT_SIGNING_DISABLED: expected a boolean" in capsys.readouterr().err


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize(
    "stdin_tty, stdout_tty",
    [(True, True), (False, True), (True, False), (False, False)],
)
def test_stdio_contract_defaults(
    plain_repo, monkeypatch, capsys, running, stdin_tty, stdout_tty
):
    monkeypatch.chdir(plain_repo)
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin_tty)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout_tty)
    monkeypatch.setattr(
        c,
        "running_containers",
        lambda: (c.Container("id", "dev", (c.Mount(plain_repo, plain_repo),)),),
    )
    c.main(
        [
            "--dry-run",
            *(["-r"] if running else ["--no-git-signing", "--no-plannotator-port"]),
            "cat",
        ]
    )
    words = shlex.split(capsys.readouterr().out)
    assert "-i" in words
    assert ("-t" in words) is (stdin_tty and stdout_tty)


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("tty", [False, True])
def test_stdio_contract_overrides(
    plain_repo, monkeypatch, capsys, running, interactive, tty
):
    monkeypatch.chdir(plain_repo)
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(
        c,
        "running_containers",
        lambda: (c.Container("id", "dev", (c.Mount(plain_repo, plain_repo),)),),
    )
    c.main(
        [
            "--dry-run",
            "--interactive" if interactive else "--no-interactive",
            "--tty" if tty else "--no-tty",
            *(["-r"] if running else ["--no-git-signing", "--no-plannotator-port"]),
            "cat",
            "--tty",
        ]
    )
    words = shlex.split(capsys.readouterr().out)
    assert ("-i" in words) is interactive
    assert ("-t" in words) is tty
    assert words[-2:] == ["cat", "--tty"]


@pytest.mark.parametrize(
    "flags", [("--interactive", "--no-interactive"), ("--tty", "--no-tty")]
)
def test_stdio_contract_conflicts(flags):
    with pytest.raises(SystemExit) as error:
        parse(*flags, "cat")
    assert error.value.code == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["-a=-e", "-a=PRIVATE_VALUE=synthetic-secret"],
        ["-a=--env=PRIVATE_VALUE=synthetic-secret"],
        ["-a=--env", "-a=PRIVATE_VALUE=synthetic-secret"],
    ],
)
def test_secret_transport_contract_literal_environment(
    plain_repo, monkeypatch, capsys, extra
):
    monkeypatch.chdir(plain_repo)
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)
    args = ["--no-git-signing", "--no-plannotator-port", *extra, "bash"]
    c.main(["--dry-run", *args])
    assert "synthetic-secret" not in capsys.readouterr().out
    captured = []
    monkeypatch.setattr(os, "execvp", lambda file, args: captured.extend(args))
    c.main(args)
    assert "synthetic-secret" in repr(captured)


def test_secret_transport_contract_known_values(plain_repo, monkeypatch, capsys):
    monkeypatch.chdir(plain_repo)
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key'quoted")
    c.main(
        [
            "--dry-run",
            "--no-git-signing",
            "--no-plannotator-port",
            "echo",
            "synthetic-key'quoted",
            "https://user:password@localhost/path",
        ]
    )
    display = capsys.readouterr().out
    assert "synthetic-key" not in display
    assert "user:password" not in display


REQUIRED_CONFIG_DIRS = (
    ".agent",
    ".pi/agent",
    ".omp/agent",
    ".agent/skills",
    ".agent/prompts",
)
PERSISTENT_STATE_DIRS = (
    ".plannotator",
    ".opencode",
    ".config/opencode",
    ".local/share/opencode",
    ".local/state/opencode",
    ".local/share/opentui",
    ".claude",
    ".local/state/claude",
)


@pytest.fixture
def agent_config(tmp_path):
    root = tmp_path / "agent config"
    for rel in REQUIRED_CONFIG_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.parametrize("rel", PERSISTENT_STATE_DIRS)
def test_persistence_contract_prepares_private_state(agent_config, rel):
    c.prepare_agent_config(agent_config, dry_run=False)
    path = agent_config / rel
    assert path.is_dir()
    assert path.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_uid == os.getuid()
    assert not (agent_config / ".opencode/bin").exists()
    argv = run_argv(agent_config_dir=agent_config)
    assert f"{path}:/home/user/{rel}" in argv
    assert not any("/.local/lib" in word for word in argv)


@pytest.mark.parametrize("rel", REQUIRED_CONFIG_DIRS)
def test_persistence_contract_missing_required_has_no_side_effects(agent_config, rel):
    import shutil

    shutil.rmtree(agent_config / rel)
    with pytest.raises(c.Error, match="required configuration directory"):
        c.prepare_agent_config(agent_config, dry_run=False)
    assert not (agent_config / ".plannotator").exists()


def test_persistence_contract_dry_run_reports_without_creation(agent_config, capsys):
    before = sorted(agent_config.rglob("*"))
    c.prepare_agent_config(agent_config, dry_run=True)
    assert sorted(agent_config.rglob("*")) == before
    report = capsys.readouterr().err
    assert all(str(agent_config / rel) in report for rel in PERSISTENT_STATE_DIRS)


@pytest.mark.parametrize(
    "rel",
    [
        ".pi/agent/auth.json",
        ".omp/agent/auth.json",
        ".claude/.credentials.json",
        ".local/share/opencode/auth.json",
    ],
)
def test_persistence_contract_preserves_selected_credentials(
    agent_config, tmp_path, monkeypatch, rel
):
    personal = tmp_path / "personal"
    personal.mkdir()
    (personal / ".claude.json").write_text("must not import")
    monkeypatch.setenv("HOME", str(personal))
    path = agent_config / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic selected credential")
    c.prepare_agent_config(agent_config, dry_run=False)
    assert path.read_text() == "synthetic selected credential"
    assert not (agent_config / ".claude/.claude.json").exists()
    assert not (agent_config / ".claude.json").exists()


def test_persistence_contract_rejects_symlinked_state_before_preparing(
    agent_config, tmp_path
):
    target = tmp_path / "external"
    target.mkdir()
    (agent_config / ".claude").symlink_to(target)
    with pytest.raises(c.Error, match="symlinked"):
        c.prepare_agent_config(agent_config, dry_run=False)
    assert not (agent_config / ".plannotator").exists()


def test_persistence_contract_rejects_wrong_owner(agent_config, monkeypatch):
    state = agent_config / ".claude"
    state.mkdir()
    original = Path.stat

    def foreign(path, **kwargs):
        info = original(path, **kwargs)
        if path == state:
            fields = list(info)
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, "stat", foreign)
    with pytest.raises(c.Error, match="not owned by invoker"):
        c.prepare_agent_config(agent_config, dry_run=False)
    assert not (agent_config / ".plannotator").exists()


def test_persistence_contract_child_order_and_cache(agent_config):
    words = run_argv(agent_config_dir=agent_config)
    assert words.index(f"{agent_config}/.pi/agent:/home/user/.pi/agent") < words.index(
        f"{agent_config}/.agent/skills:/home/user/.pi/agent/skills"
    )
    assert words.index(
        f"{agent_config}/.omp/agent:/home/user/.omp/agent"
    ) < words.index(f"{agent_config}/.agent/prompts:/home/user/.omp/agent/prompts")
    assert "dev-pre-commit:/home/user/.cache/pre-commit" in words
    assert f"{agent_config}/.pi:/home/user/.pi" not in words
    assert f"{agent_config}/.omp:/home/user/.omp" not in words


def test_workspace_contract_external_bare_roots(bare_layout):
    outside = bare_layout.parent / "outside"
    workspace = c.resolve_workspace(outside)
    assert workspace.roots == (bare_layout, outside)
    assert workspace.common_dir is None


def test_workspace_contract_linked_metadata(plain_repo):
    linked = plain_repo.parent / "linked"
    git("-C", str(plain_repo), "worktree", "add", "-b", "linked", str(linked))
    workspace = c.resolve_workspace(linked)
    assert workspace.roots == (linked,)
    assert workspace.common_dir == plain_repo / ".git"


@pytest.mark.parametrize("selection", ["ab", "abcd"])
def test_container_selection_contract_exact_before_prefix(selection):
    exact = container("ab", mount("/srv"), id="abcd")
    prefix = container("dev_container", mount("/srv/project"), id="abcdef")
    selected, _ = c.select_container(
        cwd=Path("/srv/project"), containers=(prefix, exact), name=selection
    )
    assert selected is exact


def test_container_selection_contract_ambiguous_prefix():
    first = container("one", mount("/srv"), id="abcd1234")
    second = container("two", mount("/srv"), id="abcd5678")
    with pytest.raises(c.Error, match=r"ambiguous.*one.*abcd1234.*two.*abcd5678"):
        c.select_container(
            cwd=Path("/srv/project"), containers=(first, second), name="abcd"
        )


def test_container_selection_contract_unique_prefix():
    first = container("one", mount("/srv"), id="abcd1234")
    second = container("two", mount("/srv"), id="abcd5678")
    selected, _ = c.select_container(
        cwd=Path("/srv/project"), containers=(first, second), name="abcd1"
    )
    assert selected is first


def test_container_selection_contract_exec_uses_id(plain_repo, monkeypatch):
    selected = container(
        "friendly", c.Mount(plain_repo, Path("/work")), id="immutable-id"
    )
    monkeypatch.setattr(c, "running_containers", lambda: (selected,))
    words, banner = c.exec_running(parse("-r", "cat"), cwd=plain_repo, tty=False)
    assert words[-2:] == ["immutable-id", "cat"]
    assert banner == "friendly:/work"


@pytest.mark.parametrize(
    "flag, value",
    [
        ("--cpus", "0"),
        ("--cpus", "-1"),
        ("--cpus", "1.5"),
        ("--ram-mib", "0"),
        ("--ram-mib", "-2"),
        ("--plannotator-port", "0"),
        ("--plannotator-port", "65536"),
    ],
)
def test_launch_validation_contract_ranges_no_side_effects(
    agent_config, monkeypatch, capsys, flag, value
):
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    with pytest.raises(SystemExit) as error:
        c.main(["--dry-run", flag, value, "bash"])
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert not (agent_config / ".plannotator").exists()


@pytest.mark.parametrize("rel", [".pi/agent", ".claude", ".local"])
def test_launch_validation_contract_wrong_type_before_preparation(
    agent_config, monkeypatch, rel
):
    import shutil

    path = agent_config / rel
    if path.exists():
        shutil.rmtree(path)
    path.write_text("not a directory")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))

    def forbidden(*args, **kwargs):
        pytest.fail("invalid sources must be rejected before socket probing")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    with pytest.raises(c.Error, match="directory"):
        c.new_container(parse("-k", "bash"), cwd=agent_config.parent, tty=False)
    assert not (agent_config / ".plannotator").exists()


def test_launch_validation_contract_relative_configuration(
    agent_config, monkeypatch, capsys
):
    monkeypatch.chdir(agent_config.parent)
    monkeypatch.setenv("AGENT_CONFIG_DIR", f"unused/../{agent_config.name}")
    c.main(
        [
            "--dry-run",
            "--no-git-root",
            "--no-git-signing",
            "--no-plannotator-port",
            "bash",
        ]
    )
    words = shlex.split(capsys.readouterr().out)
    assert f"{agent_config}/.agent:/home/user/.agent" in words
    assert not (agent_config / ".plannotator").exists()


@pytest.mark.parametrize("target, suffix", [(".", ""), ("..", "/agent config")])
def test_launch_validation_contract_canonicalizes_store_alias(
    agent_config, monkeypatch, target, suffix
):
    alias = agent_config.parent / "alias"
    alias.symlink_to(agent_config / target)
    monkeypatch.setenv("AGENT_CONFIG_DIR", f"{alias}{suffix}")

    words, _ = c.new_container(
        parse("--no-git-root", "--no-git-signing", "--no-plannotator-port", "bash"),
        cwd=agent_config.parent,
        tty=False,
    )

    assert f"{agent_config}/.agent:/home/user/.agent" in words
    assert (agent_config / ".plannotator").is_dir()


def test_launch_validation_contract_store_alias_preserves_state_symlink_rejection(
    agent_config, monkeypatch
):
    alias = agent_config.parent / "alias"
    alias.symlink_to(agent_config)
    (agent_config / ".claude").symlink_to(agent_config.parent)
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(alias))

    with pytest.raises(c.Error, match=r"symlinked components: .*\.claude"):
        c.new_container(
            parse("--no-git-root", "--no-git-signing", "bash"),
            cwd=agent_config.parent,
            tty=False,
        )

    assert not (agent_config / ".plannotator").exists()


def test_launch_validation_contract_store_alias_cannot_mount_home(
    agent_config, monkeypatch
):
    alias = agent_config.parent / "alias"
    alias.symlink_to(agent_config)
    monkeypatch.setenv("HOME", str(agent_config))
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(alias))

    with pytest.raises(c.Error, match="refusing to mount"):
        c.new_container(
            parse("--no-git-root", "--no-git-signing", "bash"),
            cwd=agent_config / "project",
            tty=False,
        )

    assert not (agent_config / ".plannotator").exists()


def test_launch_validation_contract_denied_root_before_state(agent_config, monkeypatch):
    monkeypatch.setenv("HOME", str(agent_config.parent))
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(agent_config))
    with pytest.raises(c.Error, match="refusing to mount"):
        c.new_container(
            parse("--no-git-root", "bash"), cwd=agent_config.parent, tty=False
        )
    assert not (agent_config / ".plannotator").exists()


@pytest.mark.parametrize("running, executable", [(False, "git"), (True, "podman")])
def test_launch_validation_contract_missing_binaries(tmp_path, running, executable):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            *(["-r"] if running else []),
            "bash",
        ],
        env={"HOME": str(tmp_path), "PATH": str(tmp_path / "empty")},
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 127
    assert executable in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("error_number, status", [(2, 127), (13, 126)])
def test_launch_validation_contract_exec_failure(
    plain_repo, monkeypatch, capsys, error_number, status
):
    monkeypatch.chdir(plain_repo)
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)

    def fail(*args, **kwargs):
        raise OSError(error_number, "fixture exec failure")

    monkeypatch.setattr(os, "execvp", fail)
    with pytest.raises(SystemExit) as error:
        c.main(["--no-git-root", "--no-git-signing", "--no-plannotator-port", "bash"])
    assert error.value.code == status
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "delay, expected",
    [(0.002, True), (0.08, False)],
    ids=["fragmented", "total-deadline"],
)
def test_tcp_signer_contract_fragmented_deadline(delay, expected):
    import time

    with socket.socket() as listener:
        listener.bind((LOCAL_HOST, 0))
        listener.listen(1)
        listener.settimeout(2)
        stopped = threading.Event()

        def serve():
            with listener.accept()[0] as connection:
                connection.settimeout(2)
                connection.recv(5)
                for byte in agent_identity_reply(1):
                    if stopped.wait(delay):
                        return
                    try:
                        connection.sendall(bytes([byte]))
                    except OSError:
                        return

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            start = time.monotonic()
            result = c.probe_tcp_signer(
                LOCAL_HOST, listener.getsockname()[1], timeout=0.25
            )
            elapsed = time.monotonic() - start
        finally:
            stopped.set()
            thread.join(timeout=3)
    assert result is expected
    assert elapsed < 0.65
    assert not thread.is_alive()


def test_tcp_signer_contract_warning_preserves_bridge(plain_repo, monkeypatch, capsys):
    monkeypatch.chdir(plain_repo)
    monkeypatch.delenv("AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(c, "KRUN_SSH_PORT", closed_tcp_port())
    c.main(["--dry-run", "-k", "--no-plannotator-port", "bash"])
    captured = capsys.readouterr()
    assert "no signer responded; bridge remains configured" in captured.err
    assert f"pasta:-T,{c.KRUN_SSH_PORT}" in captured.out


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("interactive", [False, True])
def test_workflow_fix_podman_stub_stdin_and_arguments(
    plain_repo, tmp_path, running, interactive
):
    """Verify the wrapper's handoff to a stub, without claiming Podman execution."""
    executable = tmp_path / "podman"
    entry = inspect_entry("friendly", plain_repo)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"entry = {entry!r}\n"
        "if sys.argv[1] == 'ps': print(entry['Id'])\n"
        "elif sys.argv[1] == 'inspect': print(json.dumps([entry]))\n"
        "else: print(json.dumps([sys.argv[1:], "
        "sys.stdin.read() if '-i' in sys.argv else '']))\n"
    )
    executable.chmod(0o755)
    command = ["agent", "--dry-run", "--tty", "a b"]
    options = ["-r"] if running else ["--no-git-signing", "--no-plannotator-port"]
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *options,
            "--tty",
            "--interactive" if interactive else "--no-interactive",
            *command,
        ],
        cwd=plain_repo,
        env={"HOME": str(tmp_path), "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        input="piped stdin",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    words, stdin = json.loads(result.stdout)
    assert words[-4:] == command
    assert ("-i" in words) is interactive
    assert "-t" in words
    assert stdin == ("piped stdin" if interactive else "")
    assert words[-5] == (entry["Id"] if running else "dev:latest")


@pytest.mark.parametrize("target, status", [("absent", 127), ("not-executable", 126)])
def test_workflow_fix_engine_exec_errors(tmp_path, target, status):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if target == "not-executable":
        (bindir / "podman").write_text("cannot execute")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--no-git-root",
            "--no-git-signing",
            "--no-plannotator-port",
            "bash",
        ],
        cwd=workspace,
        env={"HOME": str(tmp_path / "home"), "PATH": str(bindir)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == status
    assert "Traceback" not in result.stderr
    assert "c: error:" in result.stderr


def test_secret_transport_contract_socks_proxy_redaction():
    assert (
        c.redact_text("socks5://user:password@proxy:1080", [])
        == "socks5://***@proxy:1080"
    )


def test_secret_transport_contract_path_diagnostics(agent_config, monkeypatch, capsys):
    secret = "synthetic-path-secret"
    root = agent_config.with_name(secret)
    agent_config.rename(root)
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(root))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(root / "run"))
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    c.main(
        [
            "--dry-run",
            "--no-plannotator-port",
            "-a=--env=PRIVATE_VALUE=synthetic-path-secret",
            "bash",
        ]
    )
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "would create private state" in captured.err
    assert "signing agent socket not found" in captured.err
